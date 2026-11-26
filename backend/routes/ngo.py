"""NGO management routes blueprint for Member 3.

Covers:
    - NGO profile registration, viewing, and updating
    - NGO activity CRUD
    - Volunteer participation request listing, approval, and rejection

Integration & security notes:
    - Authentication, role checks, and database connections are NOT duplicated
      here. Connect the placeholder hooks below to Member 4's shared backend
      before registering `ngo_bp` in `backend/routes/__init__.py`.
    - Because `_extract_payload()` accepts `request.form`, CSRF protection
      (such as Flask-WTF `CSRFProtect`) must be enforced by Member 4 if
      cookie/session-based authentication is used.
"""

from functools import wraps
from flask import Blueprint, jsonify, request

from backend.models.activity import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    create_activity,
    delete_activity,
    get_activity_by_id,
    list_activities_by_ngo,
    list_requests_for_ngo,
    review_participation_request,
    update_activity,
)
from backend.models.ngo import (
    ConflictError,
    create_ngo,
    get_ngo_by_user_id,
    update_ngo_profile,
)

ngo_bp = Blueprint("ngo", __name__, url_prefix="/ngo")


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


@ngo_bp.errorhandler(IntegrationNotReadyError)
def _handle_integration_not_ready(exc):
    return jsonify({"error": str(exc), "status": "integration_pending"}), 503


def _extract_payload():
    """Read JSON body when provided, otherwise fall back to form data."""
    json_data = request.get_json(silent=True)
    if isinstance(json_data, dict):
        return json_data
    return request.form.to_dict()


def _extract_user_id(user):
    """Support either dict-style (`user['id']`) or object-style (`user.id`) user records."""
    if isinstance(user, dict):
        return user.get("id")
    return getattr(user, "id", None)


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


def _require_ngo_profile(db, user, require_approved=False):
    """Fetch the current user's NGO profile and optionally require approval."""
    user_id = _extract_user_id(user)
    if user_id is None:
        return None, (jsonify({"error": "Authenticated user ID is missing."}), 401)

    ngo = get_ngo_by_user_id(db, user_id)
    if ngo is None:
        return None, (jsonify({"error": "NGO profile not found for current user."}), 404)

    if require_approved and ngo["verification_status"] != "approved":
        return None, (
            jsonify(
                {
                    "error": (
                        "NGO must be approved before performing this operation "
                        f"(current status: {ngo['verification_status']})."
                    )
                }
            ),
            403,
        )

    return ngo, None


def _handle_request_decision(request_id, decision):
    """Shared handler for approving or rejecting a volunteer request."""
    db = get_shared_db()
    user = get_current_user()
    ngo, error_response = _require_ngo_profile(db, user, require_approved=True)
    if error_response:
        return error_response

    try:
        updated_request = review_participation_request(
            db=db,
            request_id=request_id,
            ngo_id=ngo["id"],
            decision=decision,
            reviewer_user_id=_extract_user_id(user),
        )
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ConflictError as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"message": f"Request {decision}.", "request": updated_request}), 200


# ---------------------------------------------------------------------------
# NGO Registration & Profile Routes
# ---------------------------------------------------------------------------


@ngo_bp.route("/register", methods=["POST"])
@login_required
@role_required("ngo")
def register_ngo():
    """Register an NGO profile for the authenticated NGO user."""
    db = get_shared_db()
    user = get_current_user()
    user_id = _extract_user_id(user)
    if user_id is None:
        return jsonify({"error": "Authenticated user ID is missing."}), 401

    try:
        ngo = create_ngo(db, user_id, _extract_payload())
    except ConflictError as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"message": "NGO profile registered.", "ngo": ngo}), 201


@ngo_bp.route("/profile", methods=["GET"])
@login_required
@role_required("ngo")
def view_ngo_profile():
    """Return the authenticated NGO user's profile."""
    db = get_shared_db()
    user = get_current_user()
    ngo, error_response = _require_ngo_profile(db, user)
    if error_response:
        return error_response

    return jsonify({"ngo": ngo}), 200


@ngo_bp.route("/profile", methods=["PUT", "PATCH"])
@login_required
@role_required("ngo")
def edit_ngo_profile():
    """Update the authenticated NGO user's profile."""
    db = get_shared_db()
    user = get_current_user()
    ngo, error_response = _require_ngo_profile(db, user)
    if error_response:
        return error_response

    try:
        updated_ngo = update_ngo_profile(db, ngo["id"], _extract_payload())
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"message": "NGO profile updated.", "ngo": updated_ngo}), 200


# ---------------------------------------------------------------------------
# NGO Activity CRUD Routes
# ---------------------------------------------------------------------------


@ngo_bp.route("/activities", methods=["POST"])
@login_required
@role_required("ngo")
def add_activity():
    """Create a new activity under the current approved NGO."""
    db = get_shared_db()
    user = get_current_user()
    ngo, error_response = _require_ngo_profile(db, user, require_approved=True)
    if error_response:
        return error_response

    try:
        activity = create_activity(db, ngo["id"], _extract_payload())
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"message": "Activity created.", "activity": activity}), 201


@ngo_bp.route("/activities", methods=["GET"])
@login_required
@role_required("ngo")
def list_ngo_activities():
    """List activities owned by the current NGO with pagination."""
    db = get_shared_db()
    user = get_current_user()
    ngo, error_response = _require_ngo_profile(db, user)
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
        activities = list_activities_by_ngo(
            db, ngo["id"], status=status_filter, limit=limit, offset=offset
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return (
        jsonify(
            {
                "activities": activities,
                "pagination": {"limit": limit, "offset": offset, "count": len(activities)},
            }
        ),
        200,
    )


@ngo_bp.route("/activities/<int:activity_id>", methods=["GET"])
@login_required
@role_required("ngo")
def view_ngo_activity(activity_id):
    """Retrieve a single activity owned by the current NGO."""
    db = get_shared_db()
    user = get_current_user()
    ngo, error_response = _require_ngo_profile(db, user)
    if error_response:
        return error_response

    activity = get_activity_by_id(db, activity_id, ngo_id=ngo["id"])
    if activity is None:
        return jsonify({"error": "Activity not found for this NGO."}), 404

    return jsonify({"activity": activity}), 200


@ngo_bp.route("/activities/<int:activity_id>", methods=["PUT", "PATCH"])
@login_required
@role_required("ngo")
def edit_ngo_activity(activity_id):
    """Update an activity owned by the current NGO."""
    db = get_shared_db()
    user = get_current_user()
    ngo, error_response = _require_ngo_profile(db, user)
    if error_response:
        return error_response

    try:
        activity = update_activity(db, activity_id, ngo["id"], _extract_payload())
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"message": "Activity updated.", "activity": activity}), 200


@ngo_bp.route("/activities/<int:activity_id>", methods=["DELETE"])
@login_required
@role_required("ngo")
def remove_ngo_activity(activity_id):
    """Delete an activity owned by the current NGO."""
    db = get_shared_db()
    user = get_current_user()
    ngo, error_response = _require_ngo_profile(db, user)
    if error_response:
        return error_response

    try:
        deleted = delete_activity(db, activity_id, ngo["id"])
    except LookupError as exc:
        return jsonify({"error": str(exc)}), 404

    return jsonify({"message": "Activity deleted.", "activity": deleted}), 200


# ---------------------------------------------------------------------------
# Volunteer Participation Request Approval / Rejection Routes
# ---------------------------------------------------------------------------


@ngo_bp.route("/requests", methods=["GET"])
@login_required
@role_required("ngo")
def list_volunteer_requests():
    """List volunteer participation requests for activities owned by this NGO."""
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
        requests_list = list_requests_for_ngo(
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
                "requests": requests_list,
                "pagination": {"limit": limit, "offset": offset, "count": len(requests_list)},
            }
        ),
        200,
    )


@ngo_bp.route("/requests/<int:request_id>/approve", methods=["POST"])
@login_required
@role_required("ngo")
def approve_volunteer_request(request_id):
    """Approve a pending volunteer participation request."""
    return _handle_request_decision(request_id, "approved")


@ngo_bp.route("/requests/<int:request_id>/reject", methods=["POST"])
@login_required
@role_required("ngo")
def reject_volunteer_request(request_id):
    """Reject a pending volunteer participation request."""
    return _handle_request_decision(request_id, "rejected")
