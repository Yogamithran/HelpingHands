"""Donation submission and tracking routes blueprint for Member 3.

Covers:
    - Monetary and in-kind donation submission (volunteers only)
    - Donor donation tracking and pending-donation cancellation
    - NGO received donation tracking and status updates

Integration & security notes:
    - Authentication, role checks, and database connections are NOT duplicated
      here. Connect the placeholder hooks below to Member 4's shared backend
      before registering `donation_bp` in `backend/routes/__init__.py`.
    - Because `_extract_payload()` accepts `request.form`, CSRF protection
      (such as Flask-WTF `CSRFProtect`) must be enforced by Member 4 if
      cookie/session-based authentication is used.
"""

from functools import wraps
from flask import Blueprint, jsonify, request

from backend.models.donation import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    cancel_donation_by_donor,
    create_donation,
    get_donation_by_id,
    list_donations_by_donor,
    list_donations_for_ngo,
    update_donation_status_by_ngo,
)
from backend.models.ngo import ConflictError, get_ngo_by_user_id

donation_bp = Blueprint("donation", __name__, url_prefix="/donations")


# ---------------------------------------------------------------------------
# Member 4 Integration Placeholders (replace imports/calls once ready)
# ---------------------------------------------------------------------------


class IntegrationNotReadyError(RuntimeError):
    """Raised when Member 4's shared DB or auth hook is not yet connected."""


def get_shared_db():
    """TODO (Member 4): Return the shared SQLite connection (e.g., `get_db()`)."""
    raise IntegrationNotReadyError(
        "Member 4's shared database connection (get_db) is not connected yet."
    )


def get_current_user():
    """TODO (Member 4): Return the authenticated user object/dict (e.g., `g.user` or `current_user`)."""
    raise IntegrationNotReadyError(
        "Member 4's current-user context is not connected yet."
    )


def login_required(view):
    """TODO (Member 4): Replace with Member 4's shared `@login_required` decorator."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        raise IntegrationNotReadyError(
            "Member 4's login_required decorator is not connected yet."
        )

    return wrapped


def role_required(*allowed_roles):
    """TODO (Member 4): Replace with Member 4's shared `@role_required(...)` decorator."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            raise IntegrationNotReadyError(
                f"Member 4's role_required({', '.join(allowed_roles)}) decorator is not connected yet."
            )

        return wrapped

    return decorator


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------


@donation_bp.errorhandler(IntegrationNotReadyError)
def _handle_integration_not_ready(exc):
    return jsonify({"error": str(exc), "status": "integration_pending"}), 503


def _extract_payload():
    """Read JSON body when provided, otherwise fall back to form data."""
    if request.is_json:
        json_data = request.get_json(silent=True)
        if not isinstance(json_data, dict):
            raise ValueError("Request body must be a valid JSON object.")
        return json_data
    return request.form.to_dict()


def _extract_user_field(user, field):
    """Read a field from either a dict-like or attribute-based user object."""
    if isinstance(user, dict):
        return user.get(field)
    return getattr(user, field, None)


def _parse_query_int(param_name, default=None, min_value=1, max_value=None):
    """Parse an integer query parameter strictly, raising ValueError on invalid input."""
    raw = request.args.get(param_name)
    if raw is None or raw == "":
        return default
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ValueError(f"Query parameter '{param_name}' must be an integer.") from exc
    if parsed < min_value:
        raise ValueError(f"Query parameter '{param_name}' must be at least {min_value}.")
    if max_value is not None and parsed > max_value:
        raise ValueError(f"Query parameter '{param_name}' must be at most {max_value}.")
    return parsed


def _require_authenticated_user_id(user):
    """Extract the authenticated user's ID or return a 401 response."""
    user_id = _extract_user_field(user, "id")
    if user_id is None:
        return None, (jsonify({"error": "Authenticated user ID is missing."}), 401)
    return user_id, None


def _require_ngo_profile(db, user):
    """Fetch the current user's NGO profile or return an error response."""
    user_id, error_response = _require_authenticated_user_id(user)
    if error_response:
        return None, error_response

    ngo = get_ngo_by_user_id(db, user_id)
    if ngo is None:
        return None, (jsonify({"error": "NGO profile not found for current user."}), 404)
    return ngo, None


# ---------------------------------------------------------------------------
# Donor Donation Submission & Tracking Routes
# ---------------------------------------------------------------------------


@donation_bp.route("", methods=["POST"])
@login_required
@role_required("volunteer")
def submit_donation():
    """Submit a monetary or in-kind donation as an authenticated volunteer."""
    db = get_shared_db()
    user = get_current_user()
    donor_id, error_response = _require_authenticated_user_id(user)
    if error_response:
        return error_response

    try:
        payload = _extract_payload()
        raw_name = payload.get("donor_name")
        if raw_name is None or (isinstance(raw_name, str) and not raw_name.strip()):
            fallback_name = _extract_user_field(user, "name") or _extract_user_field(user, "full_name")
            if fallback_name:
                payload["donor_name"] = fallback_name
        raw_email = payload.get("donor_email")
        if raw_email is None or (isinstance(raw_email, str) and not raw_email.strip()):
            fallback_email = _extract_user_field(user, "email")
            if fallback_email:
                payload["donor_email"] = fallback_email

        donation = create_donation(db, payload, donor_id=donor_id)
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ConflictError as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"message": "Donation submitted.", "donation": donation}), 201


@donation_bp.route("/my", methods=["GET"])
@login_required
def list_my_donations():
    """List donations submitted by the logged-in donor with pagination."""
    db = get_shared_db()
    user = get_current_user()
    donor_id, error_response = _require_authenticated_user_id(user)
    if error_response:
        return error_response

    status_filter = request.args.get("status")
    if status_filter == "":
        status_filter = None

    try:
        limit = _parse_query_int(
            "limit", default=DEFAULT_PAGE_LIMIT, min_value=1, max_value=MAX_PAGE_LIMIT
        )
        offset = _parse_query_int("offset", default=0, min_value=0)
        donations = list_donations_by_donor(
            db, donor_id, status=status_filter, limit=limit, offset=offset
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return (
        jsonify(
            {
                "donations": donations,
                "pagination": {"limit": limit, "offset": offset, "count": len(donations)},
            }
        ),
        200,
    )


@donation_bp.route("/my/<int:donation_id>", methods=["GET"])
@login_required
def view_my_donation(donation_id):
    """View a single donation submitted by the logged-in donor."""
    db = get_shared_db()
    user = get_current_user()
    donor_id, error_response = _require_authenticated_user_id(user)
    if error_response:
        return error_response

    try:
        donation = get_donation_by_id(db, donation_id, donor_id=donor_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if donation is None:
        return jsonify({"error": "Donation not found for this donor."}), 404

    return jsonify({"donation": donation}), 200


@donation_bp.route("/my/<int:donation_id>/cancel", methods=["POST"])
@login_required
def cancel_my_donation(donation_id):
    """Cancel a pending donation submitted by the logged-in donor."""
    db = get_shared_db()
    user = get_current_user()
    donor_id, error_response = _require_authenticated_user_id(user)
    if error_response:
        return error_response

    try:
        donation = cancel_donation_by_donor(db, donation_id, donor_id)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ConflictError as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"message": "Donation cancelled.", "donation": donation}), 200


# ---------------------------------------------------------------------------
# NGO Donation Tracking & Status Management Routes
# ---------------------------------------------------------------------------


@donation_bp.route("/ngo", methods=["GET"])
@login_required
@role_required("ngo")
def list_ngo_donations():
    """List donations received by the authenticated NGO with pagination."""
    db = get_shared_db()
    user = get_current_user()
    ngo, error_response = _require_ngo_profile(db, user)
    if error_response:
        return error_response

    status_filter = request.args.get("status")
    if status_filter == "":
        status_filter = None

    try:
        activity_id = _parse_query_int("activity_id", default=None, min_value=1)
        limit = _parse_query_int(
            "limit", default=DEFAULT_PAGE_LIMIT, min_value=1, max_value=MAX_PAGE_LIMIT
        )
        offset = _parse_query_int("offset", default=0, min_value=0)
        donations = list_donations_for_ngo(
            db,
            ngo_id=ngo["id"],
            activity_id=activity_id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return (
        jsonify(
            {
                "donations": donations,
                "pagination": {"limit": limit, "offset": offset, "count": len(donations)},
            }
        ),
        200,
    )


@donation_bp.route("/ngo/<int:donation_id>", methods=["GET"])
@login_required
@role_required("ngo")
def view_ngo_donation(donation_id):
    """View a single donation received by the authenticated NGO."""
    db = get_shared_db()
    user = get_current_user()
    ngo, error_response = _require_ngo_profile(db, user)
    if error_response:
        return error_response

    try:
        donation = get_donation_by_id(db, donation_id, ngo_id=ngo["id"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if donation is None:
        return jsonify({"error": "Donation not found for this NGO."}), 404

    return jsonify({"donation": donation}), 200


@donation_bp.route("/ngo/<int:donation_id>/status", methods=["PUT", "PATCH"])
@login_required
@role_required("ngo")
def update_ngo_donation_status(donation_id):
    """Update the status of a donation received by the authenticated NGO."""
    db = get_shared_db()
    user = get_current_user()
    ngo, error_response = _require_ngo_profile(db, user)
    if error_response:
        return error_response

    try:
        payload = _extract_payload()
        new_status = payload.get("status")
        if new_status is None or (isinstance(new_status, str) and not new_status.strip()):
            return jsonify({"error": "'status' is required."}), 400

        donation = update_donation_status_by_ngo(db, donation_id, ngo["id"], new_status)
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ConflictError as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"message": "Donation status updated.", "donation": donation}), 200
