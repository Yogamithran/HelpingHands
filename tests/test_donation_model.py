"""Comprehensive unit tests for Member 3's Donation model (`backend/models/donation.py`).

Note on retrieval by tracking reference:
    `backend/models/donation.py` generates and returns `transaction_ref` on
    every created, fetched, and listed donation record, but does not expose a
    standalone `get_donation_by_transaction_ref(...)` lookup function. Tests
    verify `transaction_ref` generation, uniqueness, and presence on retrieval.
"""

import sqlite3
import unittest
from unittest.mock import patch

from backend.models.activity import ACTIVITY_TABLE_SQL, create_activity
from backend.models.donation import (
    DEFAULT_PAGE_LIMIT,
    DONATION_FIELD_MAX_LENGTHS,
    DONATION_TABLE_SQL,
    MAX_DONATION_AMOUNT,
    MAX_DONATION_QUANTITY,
    MAX_PAGE_LIMIT,
    cancel_donation_by_donor,
    create_donation,
    get_donation_by_id,
    list_donations_by_donor,
    list_donations_for_ngo,
    update_donation_status_by_ngo,
)
from backend.models.ngo import NGO_TABLE_SQL, ConflictError, create_ngo


class _FailingDonationDB:
    """DB wrapper simulating SQLite write errors and verifying explicit rollback."""

    def __init__(self, real_db, fail_on_sql_prefix, exc_cls=sqlite3.OperationalError):
        self._real_db = real_db
        self._fail_on_sql_prefix = fail_on_sql_prefix.upper()
        self._exc_cls = exc_cls
        self.rolled_back = False

    def execute(self, sql, params=()):
        if sql.lstrip().upper().startswith(self._fail_on_sql_prefix):
            raise self._exc_cls("Simulated database error")
        return self._real_db.execute(sql, params)

    def commit(self):
        return self._real_db.commit()

    def rollback(self):
        self.rolled_back = True
        return self._real_db.rollback()


class TestDonationModel(unittest.TestCase):
    """Unit test suite for donation creation, tracking, validation, transitions, and rollbacks."""

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
                ("NGO Owner 1", "ngo1@example.org", "ngo"),
                ("NGO Owner 2", "ngo2@example.org", "ngo"),
                ("NGO Pending", "ngo3@example.org", "ngo"),
                ("NGO Rejected", "ngo4@example.org", "ngo"),
                ("Volunteer Donor 1", "donor1@example.org", "volunteer"),
                ("Volunteer Donor 2", "donor2@example.org", "volunteer"),
            ],
        )
        self.db.executescript(NGO_TABLE_SQL + ACTIVITY_TABLE_SQL + DONATION_TABLE_SQL)

        self.ngo1 = create_ngo(
            self.db,
            user_id=1,
            data={
                "organization_name": "Care Foundation",
                "registration_number": "NGO-201",
                "email": "care@example.org",
            },
        )
        self.ngo2 = create_ngo(
            self.db,
            user_id=2,
            data={
                "organization_name": "Hope Trust",
                "registration_number": "NGO-202",
                "email": "hope@example.org",
            },
        )
        self.pending_ngo = create_ngo(
            self.db,
            user_id=3,
            data={
                "organization_name": "Pending NGO",
                "registration_number": "NGO-203",
                "email": "pending@example.org",
            },
        )
        self.rejected_ngo = create_ngo(
            self.db,
            user_id=4,
            data={
                "organization_name": "Rejected NGO",
                "registration_number": "NGO-204",
                "email": "rejected@example.org",
            },
        )
        self.db.execute(
            "UPDATE ngos SET verification_status = 'approved' WHERE id IN (?, ?)",
            (self.ngo1["id"], self.ngo2["id"]),
        )
        self.db.execute(
            "UPDATE ngos SET verification_status = 'rejected' WHERE id = ?",
            (self.rejected_ngo["id"],),
        )
        self.db.commit()

        self.act1 = create_activity(
            self.db,
            self.ngo1["id"],
            {
                "title": "Midday Meal Drive",
                "description": "Serve hot lunches.",
                "location": "Pune",
                "event_date": "2026-12-15",
            },
        )
        self.act2 = create_activity(
            self.db,
            self.ngo2["id"],
            {
                "title": "School Kit Drive",
                "description": "Provide notebooks.",
                "location": "Mumbai",
                "event_date": "2026-12-20",
            },
        )

    def tearDown(self):
        self.db.close()

    def _monetary_payload(self, **overrides):
        payload = {
            "donor_name": "Asha Kulkarni",
            "donor_email": "asha@example.org",
            "ngo_id": self.ngo1["id"],
            "donation_type": "monetary",
            "amount": 500.556,
            "notes": "For meal kits",
        }
        payload.update(overrides)
        return payload

    def _in_kind_payload(self, **overrides):
        payload = {
            "donor_name": "Rohan Verma",
            "donor_email": "rohan@example.org",
            "ngo_id": self.ngo1["id"],
            "activity_id": self.act1["id"],
            "donation_type": "in_kind",
            "item_description": "Winter Blankets",
            "quantity": 15,
            "notes": "Clean packed",
        }
        payload.update(overrides)
        return payload

    # ------------------------------------------------------------------
    # 1 & 2. Monetary & In-kind donation creation
    # ------------------------------------------------------------------

    def test_create_monetary_donation_general_and_activity_linked(self):
        general = create_donation(self.db, self._monetary_payload(), donor_id=5)
        self.assertIsNotNone(general["id"])
        self.assertEqual(general["donor_id"], 5)
        self.assertEqual(general["ngo_id"], self.ngo1["id"])
        self.assertEqual(general["ngo_name"], "Care Foundation")
        self.assertIsNone(general["activity_id"])
        self.assertIsNone(general["activity_title"])
        self.assertEqual(general["donation_type"], "monetary")
        self.assertEqual(general["amount"], 500.56)
        self.assertEqual(general["item_description"], "")
        self.assertIsNone(general["quantity"])
        self.assertEqual(general["status"], "pending")
        self.assertRegex(general["transaction_ref"], r"^HH-[0-9A-F]{12}$")

        linked = create_donation(
            self.db,
            self._monetary_payload(activity_id=self.act1["id"], amount="250"),
            donor_id=5,
        )
        self.assertEqual(linked["activity_id"], self.act1["id"])
        self.assertEqual(linked["activity_title"], "Midday Meal Drive")
        self.assertEqual(linked["amount"], 250.0)

    def test_create_in_kind_donation_with_and_without_activity(self):
        with_activity = create_donation(self.db, self._in_kind_payload(), donor_id=5)
        self.assertEqual(with_activity["donation_type"], "in_kind")
        self.assertIsNone(with_activity["amount"])
        self.assertEqual(with_activity["item_description"], "Winter Blankets")
        self.assertEqual(with_activity["quantity"], 15)
        self.assertEqual(with_activity["activity_id"], self.act1["id"])
        self.assertEqual(with_activity["activity_title"], "Midday Meal Drive")
        self.assertEqual(with_activity["status"], "pending")

        general = create_donation(
            self.db,
            self._in_kind_payload(activity_id="", quantity="4", notes=""),
            donor_id=None,
        )
        self.assertIsNone(general["donor_id"])
        self.assertIsNone(general["activity_id"])
        self.assertEqual(general["quantity"], 4)
        self.assertEqual(general["notes"], "")

    # ------------------------------------------------------------------
    # 3. Retrieval by ID and tracking reference verification
    # ------------------------------------------------------------------

    def test_get_donation_by_id_returns_tracking_ref_and_supports_tuple_rows(self):
        created = create_donation(self.db, self._monetary_payload(), donor_id=5)
        fetched = get_donation_by_id(self.db, created["id"])
        self.assertEqual(fetched, created)
        self.assertEqual(fetched["transaction_ref"], created["transaction_ref"])

        self.db.row_factory = None
        tuple_fetched = get_donation_by_id(self.db, created["id"])
        self.assertEqual(tuple_fetched["transaction_ref"], created["transaction_ref"])
        self.assertEqual(tuple_fetched["ngo_name"], "Care Foundation")
        self.assertIsNone(get_donation_by_id(self.db, 99999))

    # ------------------------------------------------------------------
    # 4, 5, 6. Invalid amounts/quantities, missing fields, invalid types
    # ------------------------------------------------------------------

    def test_invalid_donation_amounts_and_quantities(self):
        for bad_amount in (
            None,
            "",
            True,
            False,
            0,
            -10,
            0.001,
            0.004,
            "0.001",
            float("nan"),
            float("inf"),
            float("-inf"),
            "abc",
            MAX_DONATION_AMOUNT + 0.01,
        ):
            with self.assertRaises(ValueError):
                create_donation(self.db, self._monetary_payload(amount=bad_amount), donor_id=5)

        for bad_qty in (
            None,
            "",
            0,
            -2,
            True,
            False,
            1.5,
            "2.5",
            "many",
            MAX_DONATION_QUANTITY + 1,
        ):
            with self.assertRaises(ValueError):
                create_donation(self.db, self._in_kind_payload(quantity=bad_qty), donor_id=5)

    def test_missing_required_fields_non_strings_and_max_lengths(self):
        for bad_payload in (None, [], "invalid"):
            with self.assertRaises(ValueError):
                create_donation(self.db, bad_payload, donor_id=5)

        for field in ("donor_name", "donor_email", "ngo_id", "donation_type"):
            missing = self._monetary_payload()
            del missing[field]
            with self.assertRaises(ValueError):
                create_donation(self.db, missing, donor_id=5)

            blank = self._monetary_payload(**{field: ""})
            with self.assertRaises(ValueError):
                create_donation(self.db, blank, donor_id=5)

        in_kind_no_desc = self._in_kind_payload(item_description="   ")
        with self.assertRaises(ValueError):
            create_donation(self.db, in_kind_no_desc, donor_id=5)

        for bad_email in ("plain", "a@", "@b.com", "a@b", "a@.com", "a@b."):
            with self.assertRaises(ValueError):
                create_donation(self.db, self._monetary_payload(donor_email=bad_email), donor_id=5)

        for bad_str in (123, True, ["x"]):
            with self.assertRaises(ValueError):
                create_donation(self.db, self._monetary_payload(donor_name=bad_str), donor_id=5)
            with self.assertRaises(ValueError):
                create_donation(self.db, self._monetary_payload(notes=bad_str), donor_id=5)

        for field, max_len in DONATION_FIELD_MAX_LENGTHS.items():
            oversized = "a" * max_len + "@b.com" if field == "donor_email" else "a" * (max_len + 1)
            payload = (
                self._in_kind_payload(**{field: oversized})
                if field == "item_description"
                else self._monetary_payload(**{field: oversized})
            )
            with self.assertRaises(ValueError):
                create_donation(self.db, payload, donor_id=5)

    def test_invalid_donation_types(self):
        for bad_type in ("cash", "goods", "", 123, True, None):
            with self.assertRaises(ValueError):
                create_donation(self.db, self._monetary_payload(donation_type=bad_type), donor_id=5)

    # ------------------------------------------------------------------
    # 7. Tracking reference uniqueness
    # ------------------------------------------------------------------

    def test_transaction_ref_uniqueness_and_collision_handling(self):
        d1 = create_donation(self.db, self._monetary_payload(), donor_id=5)
        d2 = create_donation(self.db, self._monetary_payload(), donor_id=5)
        self.assertNotEqual(d1["transaction_ref"], d2["transaction_ref"])

        # Schema UNIQUE constraint rejects duplicate transaction_ref
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                """
                INSERT INTO donations (
                    donor_id, donor_name, donor_email, ngo_id, donation_type,
                    amount, status, transaction_ref, created_at, updated_at
                )
                VALUES (5, 'A', 'a@b.com', ?, 'monetary', 10.0, 'pending', ?, '2026-11-26T00:00:00Z', '2026-11-26T00:00:00Z')
                """,
                (self.ngo1["id"], d1["transaction_ref"]),
            )

        # Colliding generator inside create_donation triggers rollback & ConflictError
        with patch("backend.models.donation._generate_transaction_ref", return_value=d1["transaction_ref"]):
            with self.assertRaises(ConflictError):
                create_donation(self.db, self._monetary_payload(), donor_id=5)

    # ------------------------------------------------------------------
    # 8 & 9. Pending/rejected NGOs and invalid NGO/activity references
    # ------------------------------------------------------------------

    def test_donations_to_pending_or_rejected_ngos_blocked(self):
        for blocked_ngo in (self.pending_ngo, self.rejected_ngo):
            with self.assertRaises(PermissionError):
                create_donation(
                    self.db,
                    self._monetary_payload(ngo_id=blocked_ngo["id"]),
                    donor_id=5,
                )
            with self.assertRaises(PermissionError):
                create_donation(
                    self.db,
                    self._in_kind_payload(ngo_id=blocked_ngo["id"], activity_id=None),
                    donor_id=5,
                )

    def test_invalid_ngo_and_activity_references(self):
        with self.assertRaises(LookupError):
            create_donation(self.db, self._monetary_payload(ngo_id=99999), donor_id=5)

        with self.assertRaises(LookupError):
            create_donation(self.db, self._monetary_payload(activity_id=99999), donor_id=5)

        with self.assertRaises(ValueError):
            create_donation(
                self.db,
                self._monetary_payload(ngo_id=self.ngo1["id"], activity_id=self.act2["id"]),
                donor_id=5,
            )

        for bad_id in (0, -1, True, False, 1.5, "abc"):
            with self.assertRaises(ValueError):
                create_donation(self.db, self._monetary_payload(ngo_id=bad_id), donor_id=5)
            with self.assertRaises(ValueError):
                create_donation(self.db, self._monetary_payload(activity_id=bad_id), donor_id=5)
            with self.assertRaises(ValueError):
                get_donation_by_id(self.db, bad_id)

    # ------------------------------------------------------------------
    # 10. Donor & NGO ownership restrictions and status transitions
    # ------------------------------------------------------------------

    def test_donor_and_ngo_ownership_and_status_transitions(self):
        d_mon = create_donation(self.db, self._monetary_payload(), donor_id=5)
        d_kind = create_donation(self.db, self._in_kind_payload(), donor_id=5)

        # Cross-donor isolation
        self.assertIsNone(get_donation_by_id(self.db, d_mon["id"], donor_id=6))
        self.assertEqual(list_donations_by_donor(self.db, donor_id=6), [])
        with self.assertRaises(LookupError):
            cancel_donation_by_donor(self.db, d_mon["id"], donor_id=6)

        # Cross-NGO isolation
        self.assertIsNone(get_donation_by_id(self.db, d_mon["id"], ngo_id=self.ngo2["id"]))
        self.assertEqual(list_donations_for_ngo(self.db, ngo_id=self.ngo2["id"]), [])
        with self.assertRaises(LookupError):
            update_donation_status_by_ngo(self.db, d_mon["id"], self.ngo2["id"], "completed")

        # Monetary transitions: must go pending -> completed -> acknowledged
        with self.assertRaises(ConflictError):
            update_donation_status_by_ngo(self.db, d_mon["id"], self.ngo1["id"], "acknowledged")
        with self.assertRaises(ValueError):
            update_donation_status_by_ngo(self.db, d_mon["id"], self.ngo1["id"], "bogus")
        with self.assertRaises(ValueError):
            update_donation_status_by_ngo(self.db, d_mon["id"], self.ngo1["id"], 123)

        completed = update_donation_status_by_ngo(self.db, d_mon["id"], self.ngo1["id"], "completed")
        self.assertEqual(completed["status"], "completed")

        # Donor cannot cancel a completed donation
        with self.assertRaises(ConflictError):
            cancel_donation_by_donor(self.db, d_mon["id"], donor_id=5)

        acknowledged = update_donation_status_by_ngo(
            self.db, d_mon["id"], self.ngo1["id"], "acknowledged"
        )
        self.assertEqual(acknowledged["status"], "acknowledged")
        with self.assertRaises(ConflictError):
            update_donation_status_by_ngo(self.db, d_mon["id"], self.ngo1["id"], "cancelled")

        # In-kind can transition pending -> acknowledged directly
        ack_kind = update_donation_status_by_ngo(
            self.db, d_kind["id"], self.ngo1["id"], "acknowledged"
        )
        self.assertEqual(ack_kind["status"], "acknowledged")

        # Pending donation can be cancelled by its owner donor, then no further NGO transitions
        d_cancel = create_donation(self.db, self._monetary_payload(), donor_id=5)
        cancelled = cancel_donation_by_donor(self.db, d_cancel["id"], donor_id=5)
        self.assertEqual(cancelled["status"], "cancelled")
        with self.assertRaises(ConflictError):
            cancel_donation_by_donor(self.db, d_cancel["id"], donor_id=5)
        with self.assertRaises(ConflictError):
            update_donation_status_by_ngo(self.db, d_cancel["id"], self.ngo1["id"], "completed")

    # ------------------------------------------------------------------
    # 11. Pagination and filtering
    # ------------------------------------------------------------------

    def test_pagination_and_filtering_for_donor_and_ngo(self):
        d1 = create_donation(self.db, self._monetary_payload(amount=100), donor_id=5)
        d2 = create_donation(self.db, self._in_kind_payload(quantity=2), donor_id=5)
        d3 = create_donation(
            self.db,
            self._monetary_payload(ngo_id=self.ngo2["id"], amount=300),
            donor_id=5,
        )
        update_donation_status_by_ngo(self.db, d1["id"], self.ngo1["id"], "completed")

        # Donor lists all 3 across NGOs ordered newest first
        donor_all = list_donations_by_donor(self.db, donor_id=5)
        self.assertEqual([d["id"] for d in donor_all], [d3["id"], d2["id"], d1["id"]])

        donor_page = list_donations_by_donor(self.db, donor_id=5, limit=2, offset=1)
        self.assertEqual([d["id"] for d in donor_page], [d2["id"], d1["id"]])
        self.assertEqual(
            [d["id"] for d in list_donations_by_donor(self.db, donor_id=5, status="COMPLETED")],
            [d1["id"]],
        )

        # NGO lists only its own donations with activity_id & status filters
        ngo1_all = list_donations_for_ngo(self.db, self.ngo1["id"])
        self.assertEqual([d["id"] for d in ngo1_all], [d2["id"], d1["id"]])
        self.assertEqual(
            [d["id"] for d in list_donations_for_ngo(self.db, self.ngo1["id"], activity_id=self.act1["id"])],
            [d2["id"]],
        )
        self.assertEqual(
            [d["id"] for d in list_donations_for_ngo(self.db, self.ngo1["id"], status="pending")],
            [d2["id"]],
        )
        self.assertLessEqual(DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT)

        for bad_limit in (0, -1, True, 1.5, "abc", MAX_PAGE_LIMIT + 1):
            with self.assertRaises(ValueError):
                list_donations_by_donor(self.db, donor_id=5, limit=bad_limit)
            with self.assertRaises(ValueError):
                list_donations_for_ngo(self.db, self.ngo1["id"], limit=bad_limit)

        for bad_offset in (-1, True, 1.5, "abc"):
            with self.assertRaises(ValueError):
                list_donations_by_donor(self.db, donor_id=5, offset=bad_offset)
            with self.assertRaises(ValueError):
                list_donations_for_ngo(self.db, self.ngo1["id"], offset=bad_offset)

        for bad_status in ("bogus", 123):
            with self.assertRaises(ValueError):
                list_donations_by_donor(self.db, donor_id=5, status=bad_status)
            with self.assertRaises(ValueError):
                list_donations_for_ngo(self.db, self.ngo1["id"], status=bad_status)

        for bad_act_id in (0, -1, True, 1.5, "abc"):
            with self.assertRaises(ValueError):
                list_donations_for_ngo(self.db, self.ngo1["id"], activity_id=bad_act_id)

    # ------------------------------------------------------------------
    # 12. Database rollback and constraint handling
    # ------------------------------------------------------------------

    def test_database_rollback_and_foreign_key_constraints(self):
        # Invalid donor_id FK fails IntegrityError -> rolled back & raised as ConflictError
        with self.assertRaises(ConflictError):
            create_donation(self.db, self._monetary_payload(), donor_id=99999)

        failing_insert = _FailingDonationDB(
            self.db, "INSERT INTO donations", sqlite3.OperationalError
        )
        with self.assertRaises(sqlite3.OperationalError):
            create_donation(failing_insert, self._monetary_payload(), donor_id=5)
        self.assertTrue(failing_insert.rolled_back)

        donation = create_donation(self.db, self._in_kind_payload(), donor_id=5)

        failing_update = _FailingDonationDB(
            self.db, "UPDATE donations", sqlite3.OperationalError
        )
        with self.assertRaises(sqlite3.OperationalError):
            update_donation_status_by_ngo(
                failing_update, donation["id"], self.ngo1["id"], "acknowledged"
            )
        self.assertTrue(failing_update.rolled_back)
        self.assertEqual(get_donation_by_id(self.db, donation["id"])["status"], "pending")

        failing_cancel = _FailingDonationDB(
            self.db, "UPDATE donations", sqlite3.OperationalError
        )
        with self.assertRaises(sqlite3.OperationalError):
            cancel_donation_by_donor(failing_cancel, donation["id"], donor_id=5)
        self.assertTrue(failing_cancel.rolled_back)
        self.assertEqual(get_donation_by_id(self.db, donation["id"])["status"], "pending")

        # ON DELETE SET NULL on activity_id & donor_id preserves donation record
        self.db.execute("DELETE FROM activities WHERE id = ?", (self.act1["id"],))
        self.db.execute("DELETE FROM users WHERE id = ?", (5,))
        self.db.commit()
        preserved = get_donation_by_id(self.db, donation["id"])
        self.assertIsNotNone(preserved)
        self.assertIsNone(preserved["activity_id"])
        self.assertIsNone(preserved["donor_id"])

        # ON DELETE CASCADE removes donations when NGO is deleted
        self.db.execute("DELETE FROM ngos WHERE id = ?", (self.ngo1["id"],))
        self.db.commit()
        self.assertIsNone(get_donation_by_id(self.db, donation["id"]))

        closed_db = sqlite3.connect(":memory:")
        closed_db.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            get_donation_by_id(closed_db, 1)


if __name__ == "__main__":
    unittest.main()
