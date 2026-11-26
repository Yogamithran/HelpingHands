"""Comprehensive unit tests for Member 3's NGO model (`backend/models/ngo.py`)."""

import sqlite3
import unittest

from backend.models.activity import (
    ACTIVITY_TABLE_SQL,
    PARTICIPATION_REQUEST_TABLE_SQL,
    create_activity,
    review_participation_request,
)
from backend.models.donation import DONATION_TABLE_SQL, create_donation
from backend.models.ngo import (
    NGO_FIELD_MAX_LENGTHS,
    NGO_TABLE_SQL,
    ConflictError,
    create_ngo,
    get_ngo_by_id,
    get_ngo_by_user_id,
    update_ngo_profile,
)


class TestNGOModel(unittest.TestCase):
    """Unit test suite for NGO creation, retrieval, updates, validation, and restrictions."""

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON;")
        self.db.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT, role TEXT)"
        )
        self.db.executemany(
            "INSERT INTO users (name, email, role) VALUES (?, ?, ?)",
            [
                ("NGO User 1", "ngo1@example.org", "ngo"),
                ("NGO User 2", "ngo2@example.org", "ngo"),
                ("Volunteer User", "vol1@example.org", "volunteer"),
            ],
        )
        self.db.executescript(
            NGO_TABLE_SQL
            + ACTIVITY_TABLE_SQL
            + PARTICIPATION_REQUEST_TABLE_SQL
            + DONATION_TABLE_SQL
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _base_payload(self, **overrides):
        payload = {
            "organization_name": "Helping Care Foundation",
            "registration_number": "NGO-2026-001",
            "email": "Contact@HelpingCare.org",
            "description": "Community food and education support.",
            "phone": "+91-9876543210",
            "address": "12 MG Road",
            "city": "Pune",
            "website": "https://helpingcare.org",
        }
        payload.update(overrides)
        return payload

    # ------------------------------------------------------------------
    # 1. Successful NGO creation
    # ------------------------------------------------------------------

    def test_create_ngo_with_all_fields_normalizes_and_defaults_pending(self):
        ngo = create_ngo(
            self.db,
            user_id=1,
            data=self._base_payload(
                organization_name="  Helping Care Foundation  ",
                registration_number="  NGO-2026-001  ",
                email="  Contact@HelpingCare.org  ",
            ),
        )
        self.assertIsNotNone(ngo["id"])
        self.assertEqual(ngo["user_id"], 1)
        self.assertEqual(ngo["organization_name"], "Helping Care Foundation")
        self.assertEqual(ngo["registration_number"], "NGO-2026-001")
        self.assertEqual(ngo["email"], "contact@helpingcare.org")
        self.assertEqual(ngo["website"], "https://helpingcare.org")
        self.assertEqual(ngo["verification_status"], "pending")
        self.assertTrue(ngo["created_at"])
        self.assertTrue(ngo["updated_at"])

    def test_create_ngo_with_required_fields_only(self):
        ngo = create_ngo(
            self.db,
            user_id=1,
            data={
                "organization_name": "Minimal NGO",
                "registration_number": "MIN-001",
                "email": "min@example.org",
            },
        )
        self.assertEqual(ngo["description"], "")
        self.assertEqual(ngo["phone"], "")
        self.assertEqual(ngo["address"], "")
        self.assertEqual(ngo["city"], "")
        self.assertEqual(ngo["website"], "")
        self.assertEqual(ngo["verification_status"], "pending")

    # ------------------------------------------------------------------
    # 2. Retrieving NGO details
    # ------------------------------------------------------------------

    def test_get_ngo_by_id_and_user_id(self):
        created = create_ngo(self.db, user_id=1, data=self._base_payload())

        by_id = get_ngo_by_id(self.db, created["id"])
        by_user = get_ngo_by_user_id(self.db, 1)

        self.assertEqual(by_id, created)
        self.assertEqual(by_user, created)
        self.assertIsNone(get_ngo_by_id(self.db, 9999))
        self.assertIsNone(get_ngo_by_user_id(self.db, 9999))

    def test_get_ngo_supports_tuple_rows_without_row_factory(self):
        created = create_ngo(self.db, user_id=1, data=self._base_payload())
        self.db.row_factory = None
        fetched = get_ngo_by_id(self.db, created["id"])
        self.assertEqual(fetched["organization_name"], created["organization_name"])
        self.assertEqual(fetched["email"], created["email"])

    # ------------------------------------------------------------------
    # 3. Updating NGO profile
    # ------------------------------------------------------------------

    def test_update_ngo_profile_updates_allowed_fields(self):
        created = create_ngo(self.db, user_id=1, data=self._base_payload())
        updated = update_ngo_profile(
            self.db,
            created["id"],
            {
                "organization_name": "  Updated Care Org  ",
                "city": "Mumbai",
                "website": "http://updatedcare.org/about",
                "registration_number": "SHOULD-NOT-CHANGE",
                "user_id": 2,
            },
        )
        self.assertEqual(updated["organization_name"], "Updated Care Org")
        self.assertEqual(updated["city"], "Mumbai")
        self.assertEqual(updated["website"], "http://updatedcare.org/about")
        self.assertEqual(updated["registration_number"], created["registration_number"])
        self.assertEqual(updated["user_id"], 1)

    def test_update_ngo_profile_not_found_and_empty_update(self):
        with self.assertRaises(LookupError):
            update_ngo_profile(self.db, 999, {"city": "Delhi"})

        created = create_ngo(self.db, user_id=1, data=self._base_payload())
        with self.assertRaises(ValueError):
            update_ngo_profile(self.db, created["id"], {})

    # ------------------------------------------------------------------
    # 4. Duplicate registration number, user, and email conflicts
    # ------------------------------------------------------------------

    def test_duplicate_user_conflict(self):
        create_ngo(self.db, user_id=1, data=self._base_payload())
        with self.assertRaises(ConflictError):
            create_ngo(
                self.db,
                user_id=1,
                data=self._base_payload(
                    registration_number="NGO-2026-002",
                    email="other@example.org",
                ),
            )

    def test_duplicate_registration_number_conflict(self):
        create_ngo(self.db, user_id=1, data=self._base_payload())
        with self.assertRaises(ConflictError):
            create_ngo(
                self.db,
                user_id=2,
                data=self._base_payload(
                    registration_number="NGO-2026-001",
                    email="second@example.org",
                ),
            )

    def test_duplicate_email_conflict_on_create_and_update(self):
        ngo1 = create_ngo(
            self.db,
            user_id=1,
            data=self._base_payload(email="shared@ngo.org", registration_number="REG-1"),
        )
        ngo2 = create_ngo(
            self.db,
            user_id=2,
            data=self._base_payload(email="unique2@ngo.org", registration_number="REG-2"),
        )

        # Case-insensitive duplicate email on create (for a third user)
        self.db.execute(
            "INSERT INTO users (name, email, role) VALUES (?, ?, ?)",
            ("NGO User 3", "ngo3@example.org", "ngo"),
        )
        with self.assertRaises(ConflictError):
            create_ngo(
                self.db,
                user_id=3,
                data=self._base_payload(email="SHARED@NGO.ORG", registration_number="REG-3"),
            )

        # Updating ngo2 to ngo1's email must fail with ConflictError
        with self.assertRaises(ConflictError):
            update_ngo_profile(self.db, ngo2["id"], {"email": "SHARED@ngo.org"})

        # Updating ngo1 with its own existing email must succeed
        same_email_update = update_ngo_profile(self.db, ngo1["id"], {"email": "shared@ngo.org"})
        self.assertEqual(same_email_update["email"], "shared@ngo.org")

    # ------------------------------------------------------------------
    # 5. Invalid and missing required fields
    # ------------------------------------------------------------------

    def test_invalid_payload_type_and_missing_required_fields(self):
        for bad_payload in (None, [], "invalid"):
            with self.assertRaises(ValueError):
                create_ngo(self.db, user_id=1, data=bad_payload)

        for missing_field in ("organization_name", "registration_number", "email"):
            payload = self._base_payload()
            del payload[missing_field]
            with self.assertRaises(ValueError):
                create_ngo(self.db, user_id=1, data=payload)

            blank_payload = self._base_payload(**{missing_field: "   "})
            with self.assertRaises(ValueError):
                create_ngo(self.db, user_id=1, data=blank_payload)

    def test_non_string_and_invalid_email_and_max_lengths(self):
        for bad_name in (123, True, ["Org"]):
            with self.assertRaises(ValueError):
                create_ngo(self.db, user_id=1, data=self._base_payload(organization_name=bad_name))

        for bad_email in ("plain", "user@", "@domain.com", "user@domain", "user@.com", "user@domain."):
            with self.assertRaises(ValueError):
                create_ngo(self.db, user_id=1, data=self._base_payload(email=bad_email))

        for field, max_len in NGO_FIELD_MAX_LENGTHS.items():
            oversized = (
                "https://" + "a" * max_len
                if field == "website"
                else ("a" * max_len + "@b.com" if field == "email" else "a" * (max_len + 1))
            )
            with self.assertRaises(ValueError):
                create_ngo(self.db, user_id=1, data=self._base_payload(**{field: oversized}))

        created = create_ngo(self.db, user_id=1, data=self._base_payload())
        with self.assertRaises(ValueError):
            update_ngo_profile(self.db, created["id"], {"organization_name": "   "})
        with self.assertRaises(ValueError):
            update_ngo_profile(self.db, created["id"], {"city": 456})

    # ------------------------------------------------------------------
    # 6. Website URL validation
    # ------------------------------------------------------------------

    def test_website_url_validation(self):
        for bad_url in (
            "javascript:alert(1)",
            "ftp://helpingcare.org",
            "helpingcare.org",
            "http://",
            "https://exa mple.org",
            "/relative/path",
        ):
            with self.assertRaises(ValueError):
                create_ngo(self.db, user_id=1, data=self._base_payload(website=bad_url))

        created = create_ngo(self.db, user_id=1, data=self._base_payload(website="http://example.org:8080/ngo"))
        self.assertEqual(created["website"], "http://example.org:8080/ngo")

        cleared = update_ngo_profile(self.db, created["id"], {"website": ""})
        self.assertEqual(cleared["website"], "")

    # ------------------------------------------------------------------
    # 7. NGO verification status restrictions
    # ------------------------------------------------------------------

    def test_verification_status_cannot_be_self_assigned_or_self_approved(self):
        created = create_ngo(
            self.db,
            user_id=1,
            data=self._base_payload(verification_status="approved"),
        )
        self.assertEqual(created["verification_status"], "pending")

        with self.assertRaises(ValueError):
            update_ngo_profile(self.db, created["id"], {"verification_status": "approved"})

        updated = update_ngo_profile(
            self.db,
            created["id"],
            {"city": "Bengaluru", "verification_status": "approved"},
        )
        self.assertEqual(updated["city"], "Bengaluru")
        self.assertEqual(updated["verification_status"], "pending")

    def test_pending_and_rejected_ngos_are_blocked_from_restricted_operations(self):
        pending_ngo = create_ngo(
            self.db,
            user_id=1,
            data=self._base_payload(registration_number="PEND-1", email="pend@ngo.org"),
        )
        rejected_ngo = create_ngo(
            self.db,
            user_id=2,
            data=self._base_payload(registration_number="REJ-1", email="rej@ngo.org"),
        )
        self.db.execute(
            "UPDATE ngos SET verification_status = 'rejected' WHERE id = ?",
            (rejected_ngo["id"],),
        )
        self.db.commit()

        for blocked_ngo in (pending_ngo, rejected_ngo):
            with self.assertRaises(PermissionError):
                create_activity(
                    self.db,
                    blocked_ngo["id"],
                    {
                        "title": "Blocked Drive",
                        "description": "Should not succeed",
                        "location": "Pune",
                        "event_date": "2026-12-15",
                    },
                )
            with self.assertRaises(PermissionError):
                create_donation(
                    self.db,
                    {
                        "donor_name": "Volunteer",
                        "donor_email": "vol1@example.org",
                        "ngo_id": blocked_ngo["id"],
                        "donation_type": "monetary",
                        "amount": 100,
                    },
                    donor_id=3,
                )
            with self.assertRaises(PermissionError):
                review_participation_request(
                    self.db,
                    request_id=1,
                    ngo_id=blocked_ngo["id"],
                    decision="approved",
                    reviewer_user_id=blocked_ngo["user_id"],
                )

        # Once approved, restricted operations are permitted
        self.db.execute(
            "UPDATE ngos SET verification_status = 'approved' WHERE id = ?",
            (pending_ngo["id"],),
        )
        self.db.commit()
        activity = create_activity(
            self.db,
            pending_ngo["id"],
            {
                "title": "Approved Drive",
                "description": "Now allowed",
                "location": "Pune",
                "event_date": "2026-12-15",
            },
        )
        self.assertEqual(activity["ngo_id"], pending_ngo["id"])


if __name__ == "__main__":
    unittest.main()
