"""Unit tests for NGO participation-request review and listing in `backend/models/activity.py`.

Note on scope:
    `backend/models/activity.py` implements Member 3's NGO-side participation
    request listing (`list_requests_for_ngo`) and review (`review_participation_request`)
    using the shared `PARTICIPATION_REQUEST_TABLE_SQL` contract. Volunteer-side
    request creation (`Member 2`) and volunteer-side request retrieval (`Member 2`)
    are not present in `backend/models/activity.py`, so tests here focus on
    NGO-side behavior, schema constraints, and non-duplicate edge cases beyond
    `tests/test_activity_model.py`.
"""

import sqlite3
import unittest

from backend.models.activity import (
    ACTIVITY_TABLE_SQL,
    PARTICIPATION_REQUEST_TABLE_SQL,
    create_activity,
    delete_activity,
    list_requests_for_ngo,
    review_participation_request,
)
from backend.models.ngo import NGO_TABLE_SQL, ConflictError, create_ngo


class _FailingReviewDB:
    """DB wrapper simulating SQLite write errors during participation request updates."""

    def __init__(self, real_db, fail_on_sql_prefix, exc_cls=sqlite3.OperationalError):
        self._real_db = real_db
        self._fail_on_sql_prefix = fail_on_sql_prefix.upper()
        self._exc_cls = exc_cls
        self.rolled_back = False

    def execute(self, sql, params=()):
        if sql.lstrip().upper().startswith(self._fail_on_sql_prefix):
            raise self._exc_cls("Simulated SQLite error")
        return self._real_db.execute(sql, params)

    def commit(self):
        return self._real_db.commit()

    def rollback(self):
        self.rolled_back = True
        return self._real_db.rollback()


class TestParticipationRequests(unittest.TestCase):
    """Non-duplicate unit tests for participation request review, listing, constraints, and rollbacks."""

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
                ("Volunteer A", "vola@example.org", "volunteer"),
                ("Volunteer B", "volb@example.org", "volunteer"),
                ("Volunteer C", "volc@example.org", "volunteer"),
            ],
        )
        self.db.executescript(
            NGO_TABLE_SQL + ACTIVITY_TABLE_SQL + PARTICIPATION_REQUEST_TABLE_SQL
        )

        self.ngo1 = create_ngo(
            self.db,
            user_id=1,
            data={
                "organization_name": "Care Network",
                "registration_number": "CARE-001",
                "email": "care@example.org",
            },
        )
        self.ngo2 = create_ngo(
            self.db,
            user_id=2,
            data={
                "organization_name": "Aid Alliance",
                "registration_number": "AID-002",
                "email": "aid@example.org",
            },
        )
        self.db.execute(
            "UPDATE ngos SET verification_status = 'approved' WHERE id IN (?, ?)",
            (self.ngo1["id"], self.ngo2["id"]),
        )
        self.db.commit()

        self.act1 = create_activity(
            self.db,
            self.ngo1["id"],
            {
                "title": "Community Kitchen",
                "description": "Prepare and serve dinner.",
                "location": "Pune",
                "event_date": "2026-12-10",
                "volunteers_needed": 2,
                "status": "open",
            },
        )
        self.act2 = create_activity(
            self.db,
            self.ngo2["id"],
            {
                "title": "Tree Plantation",
                "description": "Plant saplings.",
                "location": "Nagpur",
                "event_date": "2026-12-12",
                "volunteers_needed": 3,
                "status": "open",
            },
        )

    def tearDown(self):
        self.db.close()

    def _seed_request(
        self,
        activity_id,
        volunteer_id=3,
        message="Ready to volunteer",
        status="pending",
        created_at="2026-11-26T10:00:00Z",
    ):
        cursor = self.db.execute(
            """
            INSERT INTO participation_requests (activity_id, volunteer_id, message, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (activity_id, volunteer_id, message, status, created_at),
        )
        self.db.commit()
        return cursor.lastrowid

    # ------------------------------------------------------------------
    # Listing requests for an NGO
    # ------------------------------------------------------------------

    def test_list_requests_for_ngo_empty_tuple_rows_and_joined_fields(self):
        self.assertEqual(list_requests_for_ngo(self.db, self.ngo1["id"]), [])

        req_id = self._seed_request(
            self.act1["id"], volunteer_id=3, message="Weekends free", created_at="2026-11-26T09:00:00Z"
        )
        self._seed_request(self.act2["id"], volunteer_id=4, message="Other NGO")

        self.db.row_factory = None
        results = list_requests_for_ngo(self.db, self.ngo1["id"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], req_id)
        self.assertEqual(results[0]["activity_title"], "Community Kitchen")
        self.assertEqual(results[0]["message"], "Weekends free")
        self.assertEqual(results[0]["status"], "pending")
        self.assertIsNone(results[0]["reviewed_by"])
        self.assertIsNone(results[0]["reviewed_at"])

    # ------------------------------------------------------------------
    # Approving and rejecting pending requests
    # ------------------------------------------------------------------

    def test_approve_pending_request_persists_reviewer_metadata(self):
        req_id = self._seed_request(self.act1["id"], volunteer_id=3)
        approved = review_participation_request(
            self.db, req_id, self.ngo1["id"], "  APPROVED  ", reviewer_user_id=1
        )
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["reviewed_by"], 1)
        self.assertTrue(approved["reviewed_at"])

        stored = list_requests_for_ngo(self.db, self.ngo1["id"], activity_id=self.act1["id"])[0]
        self.assertEqual(stored["status"], "approved")
        self.assertEqual(stored["reviewed_by"], 1)
        self.assertEqual(stored["reviewed_at"], approved["reviewed_at"])

    def test_reject_pending_request_does_not_consume_volunteer_capacity(self):
        single_slot = create_activity(
            self.db,
            self.ngo1["id"],
            {
                "title": "Medical Camp",
                "description": "Assist registration desk.",
                "location": "Pune",
                "event_date": "2026-12-18",
                "volunteers_needed": 1,
            },
        )
        req_rejected = self._seed_request(single_slot["id"], volunteer_id=3, created_at="2026-11-26T08:00:00Z")
        req_second = self._seed_request(single_slot["id"], volunteer_id=4, created_at="2026-11-26T08:01:00Z")

        rejected = review_participation_request(
            self.db, req_rejected, self.ngo1["id"], "  REJECTED ", reviewer_user_id=1
        )
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["reviewed_by"], 1)
        self.assertTrue(rejected["reviewed_at"])

        # Rejecting the first request leaves capacity=1 available for the second volunteer
        approved = review_participation_request(
            self.db, req_second, self.ngo1["id"], "approved", reviewer_user_id=1
        )
        self.assertEqual(approved["status"], "approved")

    # ------------------------------------------------------------------
    # Repeated / invalid status transitions & non-open activity states
    # ------------------------------------------------------------------

    def test_prevent_repeated_and_invalid_status_transitions(self):
        req_rejected = self._seed_request(self.act1["id"], volunteer_id=3, status="rejected")
        req_cancelled = self._seed_request(self.act1["id"], volunteer_id=4, status="cancelled")
        req_approved = self._seed_request(self.act1["id"], volunteer_id=5, status="approved")

        for req_id, decision in (
            (req_rejected, "approved"),
            (req_rejected, "rejected"),
            (req_cancelled, "approved"),
            (req_cancelled, "rejected"),
            (req_approved, "approved"),
        ):
            with self.assertRaises(ConflictError):
                review_participation_request(
                    self.db, req_id, self.ngo1["id"], decision, reviewer_user_id=1
                )

        req_pending = self._seed_request(self.act1["id"], volunteer_id=3, status="pending")
        for bad_decision in (None, 123, True, "", "pending", "cancelled"):
            with self.assertRaises(ValueError):
                review_participation_request(
                    self.db, req_pending, self.ngo1["id"], bad_decision, reviewer_user_id=1
                )

    def test_multi_slot_capacity_limit_blocks_excess_approvals(self):
        r1 = self._seed_request(self.act1["id"], volunteer_id=3)
        r2 = self._seed_request(self.act1["id"], volunteer_id=4)
        r3 = self._seed_request(self.act1["id"], volunteer_id=5)

        self.assertEqual(
            review_participation_request(self.db, r1, self.ngo1["id"], "approved", 1)["status"],
            "approved",
        )
        self.assertEqual(
            review_participation_request(self.db, r2, self.ngo1["id"], "approved", 1)["status"],
            "approved",
        )
        with self.assertRaises(ConflictError):
            review_participation_request(self.db, r3, self.ngo1["id"], "approved", 1)

    def test_non_open_completed_and_cancelled_activities_and_deleted_activity_cascade(self):
        for non_open_status in ("completed", "cancelled"):
            act = create_activity(
                self.db,
                self.ngo1["id"],
                {
                    "title": f"Event {non_open_status}",
                    "description": "Status test",
                    "location": "Pune",
                    "event_date": "2026-12-20",
                    "volunteers_needed": 3,
                    "status": non_open_status,
                },
            )
            req_id = self._seed_request(act["id"], volunteer_id=3)
            with self.assertRaises(ConflictError):
                review_participation_request(self.db, req_id, self.ngo1["id"], "approved", 1)

        # Deleting an activity cascades and removes associated participation requests
        req_to_cascade = self._seed_request(self.act1["id"], volunteer_id=3)
        delete_activity(self.db, self.act1["id"], self.ngo1["id"])
        self.assertEqual(list_requests_for_ngo(self.db, self.ngo1["id"], activity_id=self.act1["id"]), [])
        with self.assertRaises(LookupError):
            review_participation_request(self.db, req_to_cascade, self.ngo1["id"], "approved", 1)

        # Foreign key constraint rejects orphaned requests referencing a deleted/non-existent activity
        with self.assertRaises(sqlite3.IntegrityError):
            self._seed_request(self.act1["id"], volunteer_id=3)

    # ------------------------------------------------------------------
    # Cross-NGO isolation, invalid IDs, and DB rollback
    # ------------------------------------------------------------------

    def test_cross_ngo_review_denied_without_mutating_pending_request(self):
        req_id = self._seed_request(self.act1["id"], volunteer_id=3)
        with self.assertRaises(LookupError):
            review_participation_request(self.db, req_id, self.ngo2["id"], "rejected", 2)

        record = list_requests_for_ngo(self.db, self.ngo1["id"], activity_id=self.act1["id"])[0]
        self.assertEqual(record["status"], "pending")
        self.assertIsNone(record["reviewed_by"])

    def test_invalid_ids_and_missing_records(self):
        req_id = self._seed_request(self.act1["id"], volunteer_id=3)

        for bad_id in (0, -1, True, False, 1.5, "abc", None):
            with self.assertRaises(ValueError):
                list_requests_for_ngo(self.db, bad_id)
            with self.assertRaises(ValueError):
                review_participation_request(self.db, bad_id, self.ngo1["id"], "approved", 1)
            with self.assertRaises(ValueError):
                review_participation_request(self.db, req_id, bad_id, "approved", 1)
            with self.assertRaises(ValueError):
                review_participation_request(self.db, req_id, self.ngo1["id"], "approved", bad_id)

        with self.assertRaises(LookupError):
            review_participation_request(self.db, req_id, 99999, "approved", 1)
        with self.assertRaises(LookupError):
            review_participation_request(self.db, 99999, self.ngo1["id"], "approved", 1)

    def test_database_rollback_on_review_errors(self):
        req_id = self._seed_request(self.act1["id"], volunteer_id=3)

        # Invalid reviewer_user_id triggers FK IntegrityError -> rolled back & raised as ConflictError
        with self.assertRaises(ConflictError):
            review_participation_request(
                self.db, req_id, self.ngo1["id"], "approved", reviewer_user_id=99999
            )
        stored = list_requests_for_ngo(self.db, self.ngo1["id"], activity_id=self.act1["id"])[0]
        self.assertEqual(stored["status"], "pending")
        self.assertIsNone(stored["reviewed_by"])

        # OperationalError during UPDATE triggers explicit rollback
        failing_db = _FailingReviewDB(
            self.db, "UPDATE participation_requests", sqlite3.OperationalError
        )
        with self.assertRaises(sqlite3.OperationalError):
            review_participation_request(
                failing_db, req_id, self.ngo1["id"], "rejected", reviewer_user_id=1
            )
        self.assertTrue(failing_db.rolled_back)
        stored_after = list_requests_for_ngo(self.db, self.ngo1["id"], activity_id=self.act1["id"])[0]
        self.assertEqual(stored_after["status"], "pending")


if __name__ == "__main__":
    unittest.main()
