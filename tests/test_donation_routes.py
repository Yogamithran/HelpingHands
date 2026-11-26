"""Comprehensive Flask test-client unit tests for `backend/routes/donation.py`."""

from functools import wraps
import sqlite3
import unittest

from flask import Flask, jsonify

from backend.models.activity import ACTIVITY_TABLE_SQL, create_activity
from backend.models.donation import DONATION_TABLE_SQL, create_donation
from backend.models.ngo import NGO_TABLE_SQL, create_ngo
import backend.routes.donation as donation_routes


def _unwrap_view(fn):
    """Return the innermost unwrapped route function."""
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


class TestDonationRoutes(unittest.TestCase):
    """Test suite for Member 3 donation API routes using Flask test client."""

    _ENDPOINT_ROLES = {
        "donation.submit_donation": ("volunteer",),
        "donation.list_my_donations": None,
        "donation.view_my_donation": None,
        "donation.cancel_my_donation": None,
        "donation.list_ngo_donations": ("ngo",),
        "donation.view_ngo_donation": ("ngo",),
        "donation.update_ngo_donation_status": ("ngo",),
    }

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
                ("NGO No Profile", "ngo4@example.org", "ngo"),
                ("Volunteer 1", "vol1@example.org", "volunteer"),
                ("Volunteer 2", "vol2@example.org", "volunteer"),
            ],
        )
        self.db.executescript(NGO_TABLE_SQL + ACTIVITY_TABLE_SQL + DONATION_TABLE_SQL)

        self.ngo1 = create_ngo(
            self.db,
            user_id=1,
            data={
                "organization_name": "Care Foundation",
                "registration_number": "NGO-301",
                "email": "care@example.org",
            },
        )
        self.ngo2 = create_ngo(
            self.db,
            user_id=2,
            data={
                "organization_name": "Hope Trust",
                "registration_number": "NGO-302",
                "email": "hope@example.org",
            },
        )
        self.pending_ngo = create_ngo(
            self.db,
            user_id=3,
            data={
                "organization_name": "Pending NGO",
                "registration_number": "NGO-303",
                "email": "pending@example.org",
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
                "title": "Food Distribution",
                "description": "Distribute meal packets.",
                "location": "Pune",
                "event_date": "2026-12-20",
            },
        )

        # Save original module-level hooks so each test cleans up cleanly
        self._orig_get_shared_db = donation_routes.get_shared_db
        self._orig_get_current_user = donation_routes.get_current_user

        self.active_user = {"id": 5, "name": "Volunteer 1", "email": "vol1@example.org", "role": "volunteer"}

        donation_routes.get_shared_db = lambda: self.db
        donation_routes.get_current_user = lambda: self.active_user

        self.app = Flask(__name__)
        self.app.register_blueprint(donation_routes.donation_bp)
        self._install_auth_mocks(self.app)
        self.client = self.app.test_client()

    def tearDown(self):
        donation_routes.get_shared_db = self._orig_get_shared_db
        donation_routes.get_current_user = self._orig_get_current_user
        self.db.close()

    def _install_auth_mocks(self, app):
        """Wrap registered blueprint endpoints with mock auth & role enforcement."""
        for endpoint, allowed_roles in self._ENDPOINT_ROLES.items():
            raw_view = _unwrap_view(app.view_functions[endpoint])

            def _make_wrapped(fn, roles):
                @wraps(fn)
                def wrapped(*args, **kwargs):
                    user = self.active_user
                    if user is None:
                        return jsonify({"error": "Authentication required."}), 401
                    if roles is not None and user.get("role") not in roles:
                        return jsonify({"error": "Forbidden for this role."}), 403
                    return fn(*args, **kwargs)

                return wrapped

            app.view_functions[endpoint] = _make_wrapped(raw_view, allowed_roles)

    def _seed_donation(self, donor_id=5, ngo_id=None, donation_type="monetary", amount=200.0, activity_id=None):
        target_ngo = ngo_id if ngo_id is not None else self.ngo1["id"]
        if donation_type == "monetary":
            payload = {
                "donor_name": "Volunteer 1",
                "donor_email": "vol1@example.org",
                "ngo_id": target_ngo,
                "activity_id": activity_id,
                "donation_type": "monetary",
                "amount": amount,
            }
        else:
            payload = {
                "donor_name": "Volunteer 1",
                "donor_email": "vol1@example.org",
                "ngo_id": target_ngo,
                "activity_id": activity_id,
                "donation_type": "in_kind",
                "item_description": "Blankets",
                "quantity": 6,
            }
        return create_donation(self.db, payload, donor_id=donor_id)

    # ------------------------------------------------------------------
    # 1. POST /donations – monetary & in-kind submission
    # ------------------------------------------------------------------

    def test_submit_monetary_and_in_kind_donations(self):
        # Monetary donation using authenticated user fallback for donor_name/donor_email
        resp_mon = self.client.post(
            "/donations",
            json={
                "ngo_id": self.ngo1["id"],
                "donation_type": "monetary",
                "amount": 350.75,
                "notes": "Happy to help",
            },
        )
        self.assertEqual(resp_mon.status_code, 201)
        mon_data = resp_mon.get_json()["donation"]
        self.assertEqual(mon_data["donor_id"], 5)
        self.assertEqual(mon_data["donor_name"], "Volunteer 1")
        self.assertEqual(mon_data["donor_email"], "vol1@example.org")
        self.assertEqual(mon_data["amount"], 350.75)
        self.assertEqual(mon_data["status"], "pending")
        self.assertTrue(mon_data["transaction_ref"].startswith("HH-"))

        # In-kind donation with explicit donor fields and activity_id via form payload
        resp_kind = self.client.post(
            "/donations",
            data={
                "donor_name": "Custom Donor",
                "donor_email": "custom@example.org",
                "ngo_id": str(self.ngo1["id"]),
                "activity_id": str(self.act1["id"]),
                "donation_type": "in_kind",
                "item_description": "Rice Sacks",
                "quantity": "10",
            },
        )
        self.assertEqual(resp_kind.status_code, 201)
        kind_data = resp_kind.get_json()["donation"]
        self.assertEqual(kind_data["donation_type"], "in_kind")
        self.assertEqual(kind_data["quantity"], 10)
        self.assertEqual(kind_data["activity_id"], self.act1["id"])

    # ------------------------------------------------------------------
    # 2, 3, 4. Donor tracking, detail retrieval, and cancellation
    # ------------------------------------------------------------------

    def test_donor_list_detail_and_cancel_routes(self):
        d1 = self._seed_donation(donor_id=5, amount=100)
        d2 = self._seed_donation(donor_id=6, amount=200)

        resp_list = self.client.get("/donations/my")
        self.assertEqual(resp_list.status_code, 200)
        body = resp_list.get_json()
        self.assertEqual([d["id"] for d in body["donations"]], [d1["id"]])
        self.assertEqual(body["pagination"]["count"], 1)

        resp_detail = self.client.get(f"/donations/my/{d1['id']}")
        self.assertEqual(resp_detail.status_code, 200)
        self.assertEqual(resp_detail.get_json()["donation"]["transaction_ref"], d1["transaction_ref"])

        # Donor cannot view or cancel another donor's donation
        self.assertEqual(self.client.get(f"/donations/my/{d2['id']}").status_code, 404)
        self.assertEqual(self.client.post(f"/donations/my/{d2['id']}/cancel").status_code, 404)

        resp_cancel = self.client.post(f"/donations/my/{d1['id']}/cancel")
        self.assertEqual(resp_cancel.status_code, 200)
        self.assertEqual(resp_cancel.get_json()["donation"]["status"], "cancelled")

        # Repeated cancellation returns 409 Conflict
        self.assertEqual(self.client.post(f"/donations/my/{d1['id']}/cancel").status_code, 409)

    # ------------------------------------------------------------------
    # 5, 6, 7. NGO received donations, detail, and status update routes
    # ------------------------------------------------------------------

    def test_ngo_list_detail_and_status_update_routes(self):
        d_mon = self._seed_donation(donor_id=5, ngo_id=self.ngo1["id"], donation_type="monetary")
        d_kind = self._seed_donation(donor_id=5, ngo_id=self.ngo1["id"], donation_type="in_kind")
        d_other = self._seed_donation(donor_id=5, ngo_id=self.ngo2["id"], donation_type="monetary")

        self.active_user = {"id": 1, "name": "NGO Owner 1", "email": "ngo1@example.org", "role": "ngo"}

        resp_list = self.client.get("/donations/ngo")
        self.assertEqual(resp_list.status_code, 200)
        self.assertEqual(len(resp_list.get_json()["donations"]), 2)

        resp_detail = self.client.get(f"/donations/ngo/{d_mon['id']}")
        self.assertEqual(resp_detail.status_code, 200)
        self.assertEqual(resp_detail.get_json()["donation"]["id"], d_mon["id"])

        # NGO1 cannot access or update NGO2's donation
        self.assertEqual(self.client.get(f"/donations/ngo/{d_other['id']}").status_code, 404)
        self.assertEqual(
            self.client.patch(
                f"/donations/ngo/{d_other['id']}/status", json={"status": "completed"}
            ).status_code,
            404,
        )

        # Monetary cannot jump pending -> acknowledged (409)
        resp_skip = self.client.patch(
            f"/donations/ngo/{d_mon['id']}/status", json={"status": "acknowledged"}
        )
        self.assertEqual(resp_skip.status_code, 409)

        # Monetary pending -> completed (PUT) -> acknowledged (PATCH)
        resp_complete = self.client.put(
            f"/donations/ngo/{d_mon['id']}/status", json={"status": "completed"}
        )
        self.assertEqual(resp_complete.status_code, 200)
        self.assertEqual(resp_complete.get_json()["donation"]["status"], "completed")

        resp_ack = self.client.patch(
            f"/donations/ngo/{d_mon['id']}/status", json={"status": "acknowledged"}
        )
        self.assertEqual(resp_ack.status_code, 200)
        self.assertEqual(resp_ack.get_json()["donation"]["status"], "acknowledged")

        # In-kind pending -> acknowledged directly
        resp_kind_ack = self.client.patch(
            f"/donations/ngo/{d_kind['id']}/status", json={"status": "acknowledged"}
        )
        self.assertEqual(resp_kind_ack.status_code, 200)
        self.assertEqual(resp_kind_ack.get_json()["donation"]["status"], "acknowledged")

    # ------------------------------------------------------------------
    # 8 & 9. Authentication and role-based access control
    # ------------------------------------------------------------------

    def test_authentication_required_and_role_restrictions(self):
        # Unauthenticated (401)
        self.active_user = None
        for method, path in (
            ("POST", "/donations"),
            ("GET", "/donations/my"),
            ("GET", "/donations/my/1"),
            ("POST", "/donations/my/1/cancel"),
            ("GET", "/donations/ngo"),
            ("GET", "/donations/ngo/1"),
            ("PATCH", "/donations/ngo/1/status"),
        ):
            resp = self.client.open(path, method=method)
            self.assertEqual(resp.status_code, 401, msg=f"{method} {path}")

        # User object missing ID -> 401 from _require_authenticated_user_id
        self.active_user = {"role": "volunteer", "email": "noid@example.org"}
        self.assertEqual(self.client.get("/donations/my").status_code, 401)

        # Volunteer blocked from NGO endpoints (403)
        self.active_user = {"id": 5, "role": "volunteer"}
        self.assertEqual(self.client.get("/donations/ngo").status_code, 403)
        self.assertEqual(self.client.get("/donations/ngo/1").status_code, 403)
        self.assertEqual(
            self.client.patch("/donations/ngo/1/status", json={"status": "completed"}).status_code,
            403,
        )

        # NGO role blocked from POST /donations (403)
        self.active_user = {"id": 1, "role": "ngo"}
        self.assertEqual(
            self.client.post(
                "/donations",
                json={"ngo_id": self.ngo1["id"], "donation_type": "monetary", "amount": 50},
            ).status_code,
            403,
        )

        # NGO user without NGO profile gets 404 on NGO donation routes
        self.active_user = {"id": 4, "role": "ngo"}
        self.assertEqual(self.client.get("/donations/ngo").status_code, 404)

    # ------------------------------------------------------------------
    # 10 & 11. Invalid JSON, missing fields, invalid IDs, and 400/403/404/409/503
    # ------------------------------------------------------------------

    def test_invalid_json_missing_fields_invalid_ids_and_error_codes(self):
        # Malformed JSON & non-object JSON -> 400
        resp_bad_json = self.client.post(
            "/donations", data="{not valid json", content_type="application/json"
        )
        self.assertEqual(resp_bad_json.status_code, 400)

        resp_list_json = self.client.post("/donations", json=["not", "an", "object"])
        self.assertEqual(resp_list_json.status_code, 400)

        # Missing required fields -> 400
        self.assertEqual(self.client.post("/donations", json={}).status_code, 400)

        # Pending NGO donation target -> 403
        resp_pending = self.client.post(
            "/donations",
            json={"ngo_id": self.pending_ngo["id"], "donation_type": "monetary", "amount": 50},
        )
        self.assertEqual(resp_pending.status_code, 403)

        # Non-existent NGO -> 404
        resp_missing_ngo = self.client.post(
            "/donations",
            json={"ngo_id": 99999, "donation_type": "monetary", "amount": 50},
        )
        self.assertEqual(resp_missing_ngo.status_code, 404)

        # Invalid donation_id=0 -> 400, non-numeric /my/abc -> 404
        self.assertEqual(self.client.get("/donations/my/0").status_code, 400)
        self.assertEqual(self.client.post("/donations/my/0/cancel").status_code, 400)
        self.assertEqual(self.client.get("/donations/my/abc").status_code, 404)

        # NGO status route malformed JSON, missing status, invalid status, and donation_id=0 -> 400
        d1 = self._seed_donation(donor_id=5, ngo_id=self.ngo1["id"])
        self.active_user = {"id": 1, "role": "ngo"}
        self.assertEqual(
            self.client.patch(
                f"/donations/ngo/{d1['id']}/status",
                data="{broken",
                content_type="application/json",
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.patch(f"/donations/ngo/{d1['id']}/status", json={}).status_code,
            400,
        )
        self.assertEqual(
            self.client.patch(f"/donations/ngo/{d1['id']}/status", json={"status": "bad"}).status_code,
            400,
        )
        self.assertEqual(self.client.get("/donations/ngo/0").status_code, 400)

    def test_unwired_integration_placeholders_return_503(self):
        donation_routes.get_shared_db = self._orig_get_shared_db
        donation_routes.get_current_user = self._orig_get_current_user

        raw_app = Flask(__name__)
        raw_app.register_blueprint(donation_routes.donation_bp)
        raw_client = raw_app.test_client()

        for method, path in (
            ("POST", "/donations"),
            ("GET", "/donations/my"),
            ("GET", "/donations/my/1"),
            ("POST", "/donations/my/1/cancel"),
            ("GET", "/donations/ngo"),
            ("GET", "/donations/ngo/1"),
            ("PATCH", "/donations/ngo/1/status"),
        ):
            resp = raw_client.open(path, method=method, json={})
            self.assertEqual(resp.status_code, 503, msg=f"{method} {path}")
            self.assertEqual(resp.get_json()["status"], "integration_pending")

    # ------------------------------------------------------------------
    # 12. Pagination and filtering
    # ------------------------------------------------------------------

    def test_pagination_and_filtering_on_donor_and_ngo_routes(self):
        d1 = self._seed_donation(donor_id=5, ngo_id=self.ngo1["id"], amount=100, activity_id=self.act1["id"])
        d2 = self._seed_donation(donor_id=5, ngo_id=self.ngo1["id"], donation_type="in_kind")
        d3 = self._seed_donation(donor_id=5, ngo_id=self.ngo2["id"], amount=300)

        self.active_user = {"id": 1, "role": "ngo"}
        self.client.patch(f"/donations/ngo/{d1['id']}/status", json={"status": "completed"})

        # Donor pagination & status filter
        self.active_user = {"id": 5, "role": "volunteer"}
        resp_page = self.client.get("/donations/my?limit=1&offset=1")
        self.assertEqual(resp_page.status_code, 200)
        page_json = resp_page.get_json()
        self.assertEqual([d["id"] for d in page_json["donations"]], [d2["id"]])
        self.assertEqual(page_json["pagination"], {"limit": 1, "offset": 1, "count": 1})

        resp_status = self.client.get("/donations/my?status=completed")
        self.assertEqual(resp_status.status_code, 200)
        self.assertEqual([d["id"] for d in resp_status.get_json()["donations"]], [d1["id"]])

        # Invalid query parameters -> 400
        for bad_query in ("?limit=0", "?limit=101", "?limit=abc", "?offset=-1", "?offset=xyz", "?status=bad"):
            self.assertEqual(self.client.get(f"/donations/my{bad_query}").status_code, 400)

        # NGO filtering by activity_id, status, and pagination
        self.active_user = {"id": 1, "role": "ngo"}
        resp_ngo_act = self.client.get(f"/donations/ngo?activity_id={self.act1['id']}")
        self.assertEqual(resp_ngo_act.status_code, 200)
        self.assertEqual([d["id"] for d in resp_ngo_act.get_json()["donations"]], [d1["id"]])

        resp_ngo_page = self.client.get("/donations/ngo?limit=1&offset=1")
        self.assertEqual(resp_ngo_page.status_code, 200)
        self.assertEqual([d["id"] for d in resp_ngo_page.get_json()["donations"]], [d1["id"]])

        for bad_ngo_query in ("?activity_id=abc", "?activity_id=0", "?limit=abc", "?offset=-2", "?status=bad"):
            self.assertEqual(self.client.get(f"/donations/ngo{bad_ngo_query}").status_code, 400)


if __name__ == "__main__":
    unittest.main()
