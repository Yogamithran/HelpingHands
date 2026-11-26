"""Comprehensive unit tests for Member 3's Activity model (`backend/models/activity.py`)."""

import sqlite3
import unittest

from backend.models.activity import (
    ACTIVITY_FIELD_MAX_LENGTHS,
    ACTIVITY_TABLE_SQL,
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    MAX_VOLUNTEERS_NEEDED,
    PARTICIPATION_REQUEST_TABLE_SQL,
    create_activity,
    delete_activity,
    get_activity_by_id,
    list_activities_by_ngo,
    list_requests_for_ngo,
    review_participation_request,
    update_activity,
)
from backend.models.ngo import NGO_TABLE_SQL, ConflictError, create_ngo


class _FailingDB:
    """Minimal DB wrapper simulating sqlite3 write failures and verifying rollback."""

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


class TestActivityModel(unittest.TestCase):
    """Unit test suite for Activity CRUD, validation, ownership, capacity, and DB errors."""

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
                ("Volunteer 1", "vol1@example.org", "volunteer"),
                ("Volunteer 2", "vol2@example.org", "volunteer"),
            ],
        )
        self.db.executescript(
            NGO_TABLE_SQL + ACTIVITY_TABLE_SQL + PARTICIPATION_REQUEST_TABLE_SQL
        )

        self.ngo1 = create_ngo(
            self.db,
            user_id=1,
            data={
                "organization_name": "Care Foundation",
                "registration_number": "NGO-101",
                "email": "care@example.org",
            },
        )
        self.ngo2 = create_ngo(
            self.db,
            user_id=2,
            data={
                "organization_name": "Hope Trust",
                "registration_number": "NGO-102",
                "email": "hope@example.org",
            },
        )
        self.pending_ngo = create_ngo(
            self.db,
            user_id=3,
            data={
                "organization_name": "Pending Org",
                "registration_number": "NGO-103",
                "email": "pending@example.org",
            },
        )
        self.rejected_ngo = create_ngo(
            self.db,
            user_id=4,
            data={
                "organization_name": "Rejected Org",
                "registration_number": "NGO-104",
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

    def tearDown(self):
        self.db.close()

    def _base_activity(self, **overrides):
        payload = {
            "title": "Winter Blanket Drive",
            "description": "Distribute warm blankets to shelters.",
            "category": "Relief",
            "location": "Pune Station",
            "event_date": "2026-12-20",
            "volunteers_needed": 5,
            "status": "open",
        }
        payload.update(overrides)
        return payload

    def _insert_request(self, activity_id, volunteer_id=5, status="pending", created_at="2026-11-26T00:00:00Z"):
        cursor = self.db.execute(
            """
            INSERT INTO participation_requests (activity_id, volunteer_id, message, status, created_at)
            VALUES (?, ?, 'Count me in', ?, ?)
            """,
            (activity_id, volunteer_id, status, created_at),
        )
        self.db.commit()
        return cursor.lastrowid

    # ------------------------------------------------------------------
    # 1. Activity creation and retrieval
    # ------------------------------------------------------------------

    def test_create_and_retrieve_activity_with_all_and_minimal_fields(self):
        created = create_activity(
            self.db,
            self.ngo1["id"],
            self._base_activity(
                title="  Winter Blanket Drive  ",
                location="  Pune Station  ",
                status="OPEN",
            ),
        )
        self.assertIsNotNone(created["id"])
        self.assertEqual(created["ngo_id"], self.ngo1["id"])
        self.assertEqual(created["title"], "Winter Blanket Drive")
        self.assertEqual(created["location"], "Pune Station")
        self.assertEqual(created["volunteers_needed"], 5)
        self.assertEqual(created["status"], "open")
        self.assertTrue(created["created_at"])
        self.assertTrue(created["updated_at"])

        minimal = create_activity(
            self.db,
            self.ngo1["id"],
            {
                "title": "Book Collection",
                "description": "Collect school textbooks.",
                "location": "Kothrud",
                "event_date": "2026-12-25",
            },
        )
        self.assertEqual(minimal["category"], "")
        self.assertEqual(minimal["volunteers_needed"], 1)
        self.assertEqual(minimal["status"], "open")

        self.assertEqual(get_activity_by_id(self.db, created["id"]), created)
        self.assertEqual(
            get_activity_by_id(self.db, created["id"], ngo_id=self.ngo1["id"]),
            created,
        )
        self.assertIsNone(get_activity_by_id(self.db, 99999))

    def test_get_activity_supports_tuple_rows_without_row_factory(self):
        created = create_activity(self.db, self.ngo1["id"], self._base_activity())
        self.db.row_factory = None
        fetched = get_activity_by_id(self.db, created["id"])
        self.assertEqual(fetched["title"], created["title"])
        self.assertEqual(fetched["volunteers_needed"], 5)

    # ------------------------------------------------------------------
    # 2. Activity update and deletion
    # ------------------------------------------------------------------

    def test_update_and_delete_activity(self):
        created = create_activity(self.db, self.ngo1["id"], self._base_activity())
        updated = update_activity(
            self.db,
            created["id"],
            self.ngo1["id"],
            {
                "title": "  Updated Blanket Drive  ",
                "volunteers_needed": "12",
                "status": "closed",
                "event_date": "2027-01-10",
            },
        )
        self.assertEqual(updated["title"], "Updated Blanket Drive")
        self.assertEqual(updated["volunteers_needed"], 12)
        self.assertEqual(updated["status"], "closed")
        self.assertEqual(updated["event_date"], "2027-01-10")

        deleted = delete_activity(self.db, created["id"], self.ngo1["id"])
        self.assertEqual(deleted["id"], created["id"])
        self.assertIsNone(get_activity_by_id(self.db, created["id"]))

        with self.assertRaises(LookupError):
            update_activity(self.db, created["id"], self.ngo1["id"], {"title": "Ghost"})
        with self.assertRaises(LookupError):
            delete_activity(self.db, created["id"], self.ngo1["id"])

    # ------------------------------------------------------------------
    # 3. Invalid activity data and missing fields
    # ------------------------------------------------------------------

    def test_invalid_payloads_missing_fields_and_type_checks(self):
        for bad_payload in (None, [], "bad"):
            with self.assertRaises(ValueError):
                create_activity(self.db, self.ngo1["id"], bad_payload)

        for field in ("title", "description", "location", "event_date"):
            missing = self._base_activity()
            del missing[field]
            with self.assertRaises(ValueError):
                create_activity(self.db, self.ngo1["id"], missing)

            blank = self._base_activity(**{field: "   "})
            with self.assertRaises(ValueError):
                create_activity(self.db, self.ngo1["id"], blank)

        for field in ("title", "description", "category", "location", "event_date", "status"):
            with self.assertRaises(ValueError):
                create_activity(self.db, self.ngo1["id"], self._base_activity(**{field: 123}))
            with self.assertRaises(ValueError):
                create_activity(self.db, self.ngo1["id"], self._base_activity(**{field: True}))

        with self.assertRaises(ValueError):
            create_activity(self.db, self.ngo1["id"], self._base_activity(status="archived"))

        for field, max_len in ACTIVITY_FIELD_MAX_LENGTHS.items():
            with self.assertRaises(ValueError):
                create_activity(
                    self.db,
                    self.ngo1["id"],
                    self._base_activity(**{field: "x" * (max_len + 1)}),
                )

        created = create_activity(self.db, self.ngo1["id"], self._base_activity())
        for bad_update in ({}, {"unknown": "ignored"}, {"title": "   "}, {"status": "bad"}):
            with self.assertRaises(ValueError):
                update_activity(self.db, created["id"], self.ngo1["id"], bad_update)

    # ------------------------------------------------------------------
    # 4. Invalid dates and volunteer capacity
    # ------------------------------------------------------------------

    def test_event_date_validation(self):
        for bad_date in ("2026-12-1", "20-12-2026", "2026/12/20", "2026-02-30", "2025-02-29", "tomorrow"):
            with self.assertRaises(ValueError):
                create_activity(self.db, self.ngo1["id"], self._base_activity(event_date=bad_date))

        leap = create_activity(self.db, self.ngo1["id"], self._base_activity(event_date="2024-02-29"))
        self.assertEqual(leap["event_date"], "2024-02-29")

    def test_volunteers_needed_validation_and_request_capacity_enforcement(self):
        for bad_cap in (0, -3, True, False, 1.5, "2.5", "abc", MAX_VOLUNTEERS_NEEDED + 1):
            with self.assertRaises(ValueError):
                create_activity(
                    self.db,
                    self.ngo1["id"],
                    self._base_activity(volunteers_needed=bad_cap),
                )

        act = create_activity(self.db, self.ngo1["id"], self._base_activity(volunteers_needed=1))
        req1 = self._insert_request(act["id"], volunteer_id=5, created_at="2026-11-26T00:00:00Z")
        req2 = self._insert_request(act["id"], volunteer_id=6, created_at="2026-11-26T00:01:00Z")

        approved = review_participation_request(self.db, req1, self.ngo1["id"], "approved", 1)
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["reviewed_by"], 1)

        with self.assertRaises(ConflictError):
            review_participation_request(self.db, req2, self.ngo1["id"], "approved", 1)

        # Re-reviewing an already-approved request raises ConflictError
        with self.assertRaises(ConflictError):
            review_participation_request(self.db, req1, self.ngo1["id"], "rejected", 1)

        # Rejection still works for a pending request even when capacity is full
        rejected = review_participation_request(self.db, req2, self.ngo1["id"], "rejected", 1)
        self.assertEqual(rejected["status"], "rejected")

        # Non-open activity blocks approval
        closed_act = create_activity(
            self.db,
            self.ngo1["id"],
            self._base_activity(title="Closed Event", status="closed", volunteers_needed=10),
        )
        closed_req = self._insert_request(closed_act["id"], volunteer_id=5)
        with self.assertRaises(ConflictError):
            review_participation_request(self.db, closed_req, self.ngo1["id"], "approved", 1)

        with self.assertRaises(ValueError):
            review_participation_request(self.db, closed_req, self.ngo1["id"], "maybe", 1)

    # ------------------------------------------------------------------
    # 5. NGO ownership restrictions
    # ------------------------------------------------------------------

    def test_ngo_ownership_isolation_across_crud_and_requests(self):
        ngo1_act = create_activity(self.db, self.ngo1["id"], self._base_activity())
        ngo2_act = create_activity(self.db, self.ngo2["id"], self._base_activity(title="Hope Drive"))
        req1 = self._insert_request(ngo1_act["id"], volunteer_id=5)

        self.assertIsNone(get_activity_by_id(self.db, ngo1_act["id"], ngo_id=self.ngo2["id"]))

        with self.assertRaises(LookupError):
            update_activity(self.db, ngo1_act["id"], self.ngo2["id"], {"title": "Hijacked"})

        with self.assertRaises(LookupError):
            delete_activity(self.db, ngo1_act["id"], self.ngo2["id"])

        with self.assertRaises(LookupError):
            review_participation_request(self.db, req1, self.ngo2["id"], "approved", 2)

        ngo2_activities = list_activities_by_ngo(self.db, self.ngo2["id"])
        self.assertEqual([a["id"] for a in ngo2_activities], [ngo2_act["id"]])
        self.assertEqual(list_requests_for_ngo(self.db, self.ngo2["id"]), [])

    # ------------------------------------------------------------------
    # 6. Pending / rejected NGO restrictions
    # ------------------------------------------------------------------

    def test_pending_and_rejected_ngos_cannot_create_activities_or_review_requests(self):
        ngo1_act = create_activity(self.db, self.ngo1["id"], self._base_activity())
        req1 = self._insert_request(ngo1_act["id"], volunteer_id=5)

        with self.assertRaises(LookupError):
            create_activity(self.db, 99999, self._base_activity())

        for blocked in (self.pending_ngo, self.rejected_ngo):
            with self.assertRaises(PermissionError):
                create_activity(self.db, blocked["id"], self._base_activity())
            with self.assertRaises(PermissionError):
                review_participation_request(
                    self.db, req1, blocked["id"], "approved", blocked["user_id"]
                )

    # ------------------------------------------------------------------
    # 7. Pagination and filtering
    # ------------------------------------------------------------------

    def test_pagination_and_filtering_for_activities_and_requests(self):
        a1 = create_activity(
            self.db,
            self.ngo1["id"],
            self._base_activity(title="A1", event_date="2026-12-03", status="open"),
        )
        a2 = create_activity(
            self.db,
            self.ngo1["id"],
            self._base_activity(title="A2", event_date="2026-12-01", status="open"),
        )
        a3 = create_activity(
            self.db,
            self.ngo1["id"],
            self._base_activity(title="A3", event_date="2026-12-02", status="completed"),
        )

        # Ordered by event_date ASC: a2 (Dec 1), a3 (Dec 2), a1 (Dec 3)
        all_acts = list_activities_by_ngo(self.db, self.ngo1["id"])
        self.assertEqual([a["id"] for a in all_acts], [a2["id"], a3["id"], a1["id"]])

        page = list_activities_by_ngo(self.db, self.ngo1["id"], limit=2, offset=1)
        self.assertEqual([a["id"] for a in page], [a3["id"], a1["id"]])

        open_only = list_activities_by_ngo(self.db, self.ngo1["id"], status="OPEN")
        self.assertEqual([a["id"] for a in open_only], [a2["id"], a1["id"]])

        r1 = self._insert_request(a1["id"], volunteer_id=5, status="pending", created_at="2026-11-26T00:00:00Z")
        r2 = self._insert_request(a2["id"], volunteer_id=6, status="approved", created_at="2026-11-26T00:01:00Z")
        r3 = self._insert_request(a2["id"], volunteer_id=5, status="pending", created_at="2026-11-26T00:02:00Z")

        self.assertEqual(
            [r["id"] for r in list_requests_for_ngo(self.db, self.ngo1["id"], limit=2, offset=0)],
            [r3, r2],
        )
        self.assertEqual(
            [r["id"] for r in list_requests_for_ngo(self.db, self.ngo1["id"], activity_id=a2["id"], status="pending")],
            [r3],
        )
        self.assertEqual(
            [r["id"] for r in list_requests_for_ngo(self.db, self.ngo1["id"], status="approved")],
            [r2],
        )
        self.assertLessEqual(DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT)

        for bad_limit in (0, -1, True, 1.5, "abc", MAX_PAGE_LIMIT + 1):
            with self.assertRaises(ValueError):
                list_activities_by_ngo(self.db, self.ngo1["id"], limit=bad_limit)
            with self.assertRaises(ValueError):
                list_requests_for_ngo(self.db, self.ngo1["id"], limit=bad_limit)

        for bad_offset in (-1, True, 1.5, "abc"):
            with self.assertRaises(ValueError):
                list_activities_by_ngo(self.db, self.ngo1["id"], offset=bad_offset)
            with self.assertRaises(ValueError):
                list_requests_for_ngo(self.db, self.ngo1["id"], offset=bad_offset)

        for bad_status in ("bogus", 123):
            with self.assertRaises(ValueError):
                list_activities_by_ngo(self.db, self.ngo1["id"], status=bad_status)
            with self.assertRaises(ValueError):
                list_requests_for_ngo(self.db, self.ngo1["id"], status=bad_status)

        for bad_activity_id in (0, -1, True, 1.5, "abc"):
            with self.assertRaises(ValueError):
                list_requests_for_ngo(self.db, self.ngo1["id"], activity_id=bad_activity_id)

    # ------------------------------------------------------------------
    # 8. Database error handling
    # ------------------------------------------------------------------

    def test_database_errors_rollback_cleanly_and_do_not_leave_partial_state(self):
        act = create_activity(self.db, self.ngo1["id"], self._base_activity())
        req_id = self._insert_request(act["id"], volunteer_id=5)

        failing_insert = _FailingDB(self.db, "INSERT INTO activities", sqlite3.IntegrityError)
        with self.assertRaises(ConflictError):
            create_activity(failing_insert, self.ngo1["id"], self._base_activity())
        self.assertTrue(failing_insert.rolled_back)

        failing_update = _FailingDB(self.db, "UPDATE activities", sqlite3.OperationalError)
        with self.assertRaises(sqlite3.OperationalError):
            update_activity(failing_update, act["id"], self.ngo1["id"], {"title": "Should Fail"})
        self.assertTrue(failing_update.rolled_back)
        self.assertEqual(get_activity_by_id(self.db, act["id"])["title"], "Winter Blanket Drive")

        failing_delete = _FailingDB(self.db, "DELETE FROM activities", sqlite3.IntegrityError)
        with self.assertRaises(ConflictError):
            delete_activity(failing_delete, act["id"], self.ngo1["id"])
        self.assertTrue(failing_delete.rolled_back)
        self.assertIsNotNone(get_activity_by_id(self.db, act["id"]))

        # Closed database connection propagates ProgrammingError cleanly
        closed_db = sqlite3.connect(":memory:")
        closed_db.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            get_activity_by_id(closed_db, act["id"])

        # Missing request raises LookupError without mutating DB
        with self.assertRaises(LookupError):
            review_participation_request(self.db, 99999, self.ngo1["id"], "approved", 1)
        self.assertEqual(
            list_requests_for_ngo(self.db, self.ngo1["id"], activity_id=act["id"])[0]["id"],
            req_id,
        )


if __name__ == "__main__":
    unittest.main()
