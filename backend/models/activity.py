"""NGO activity CRUD and participation-request review module for Member 3.

Integration note:
    This module intentionally does NOT open its own SQLite connection or create
    tables at import time. Every database function expects Member 4's shared
    PEP 249 SQLite connection (`db`) to be passed in from the route layer.
"""

from datetime import datetime, timezone
import re
import sqlite3

from backend.models.ngo import ConflictError, get_ngo_by_id

ACTIVITY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ngo_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT DEFAULT '',
    location TEXT NOT NULL,
    event_date TEXT NOT NULL,
    volunteers_needed INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (ngo_id) REFERENCES ngos (id) ON DELETE CASCADE
);
"""

# Reference contract for the shared table created by Member 2 / Member 4.
PARTICIPATION_REQUEST_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS participation_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL,
    volunteer_id INTEGER NOT NULL,
    message TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    reviewed_by INTEGER,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (activity_id) REFERENCES activities (id) ON DELETE CASCADE,
    FOREIGN KEY (volunteer_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (reviewed_by) REFERENCES users (id)
);
"""

ACTIVITY_COLUMNS = (
    "id",
    "ngo_id",
    "title",
    "description",
    "category",
    "location",
    "event_date",
    "volunteers_needed",
    "status",
    "created_at",
    "updated_at",
)

REQUEST_COLUMNS = (
    "id",
    "activity_id",
    "activity_title",
    "volunteer_id",
    "message",
    "status",
    "reviewed_by",
    "reviewed_at",
    "created_at",
)

REQUIRED_ACTIVITY_FIELDS = ("title", "description", "location", "event_date")
UPDATABLE_ACTIVITY_FIELDS = (
    "title",
    "description",
    "category",
    "location",
    "event_date",
    "volunteers_needed",
    "status",
)

ACTIVITY_FIELD_MAX_LENGTHS = {
    "title": 150,
    "description": 2000,
    "category": 100,
    "location": 200,
}

MAX_VOLUNTEERS_NEEDED = 10_000
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100

VALID_ACTIVITY_STATUSES = frozenset({"open", "closed", "completed", "cancelled"})
VALID_REQUEST_STATUSES = frozenset({"pending", "approved", "rejected", "cancelled"})
VALID_REVIEW_DECISIONS = frozenset({"approved", "rejected"})

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _utc_now_iso():
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _serialize_row(columns, row):
    """Map a database row matching `columns` into a dictionary."""
    if row is None:
        return None
    if isinstance(row, dict):
        return {col: row.get(col) for col in columns}
    return {col: row[idx] for idx, col in enumerate(columns)}


def _parse_strict_int(value, field_name, min_value=1, max_value=None):
    """Parse an integer while rejecting booleans and floating-point values."""
    if isinstance(value, (bool, float)):
        raise ValueError(f"'{field_name}' must be a whole integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'{field_name}' must be a whole integer.") from exc
    if parsed < min_value:
        raise ValueError(f"'{field_name}' must be at least {min_value}.")
    if max_value is not None and parsed > max_value:
        raise ValueError(f"'{field_name}' must be at most {max_value}.")
    return parsed


def _validate_event_date(value):
    """Validate strict YYYY-MM-DD calendar date formatting."""
    if not _ISO_DATE_RE.fullmatch(value):
        raise ValueError("'event_date' must use YYYY-MM-DD format.")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("'event_date' is not a valid calendar date.") from exc
    return value


def _validate_pagination(limit, offset):
    """Validate pagination limit and offset bounds."""
    clean_limit = _parse_strict_int(limit, "limit", min_value=1, max_value=MAX_PAGE_LIMIT)
    clean_offset = _parse_strict_int(offset, "offset", min_value=0)
    return clean_limit, clean_offset


def _require_approved_ngo(db, ngo_id):
    """Ensure the NGO exists and has been approved by an administrator."""
    ngo = get_ngo_by_id(db, ngo_id)
    if ngo is None:
        raise LookupError("NGO profile not found.")
    if ngo["verification_status"] != "approved":
        raise PermissionError(
            f"NGO must be approved before performing this operation (status: {ngo['verification_status']})."
        )
    return ngo


def validate_activity_payload(data, is_update=False):
    """Validate and normalize NGO activity creation or update payloads."""
    if not isinstance(data, dict):
        raise ValueError("Invalid activity payload.")

    cleaned = {}
    if not is_update:
        for field in REQUIRED_ACTIVITY_FIELDS:
            raw = data.get(field)
            if raw is not None and not isinstance(raw, str):
                raise ValueError(f"'{field}' must be a string.")
            value = "" if raw is None else raw.strip()
            if not value:
                raise ValueError(f"'{field}' is required.")
            cleaned[field] = value

    for field in UPDATABLE_ACTIVITY_FIELDS:
        if field not in data or data[field] is None:
            continue

        if field == "volunteers_needed":
            cleaned[field] = _parse_strict_int(
                data[field],
                "volunteers_needed",
                min_value=1,
                max_value=MAX_VOLUNTEERS_NEEDED,
            )
        elif field == "status":
            if not isinstance(data[field], str):
                raise ValueError("'status' must be a string.")
            status_val = data[field].strip().lower()
            if status_val not in VALID_ACTIVITY_STATUSES:
                raise ValueError(
                    f"'status' must be one of: {', '.join(sorted(VALID_ACTIVITY_STATUSES))}."
                )
            cleaned[field] = status_val
        elif field == "event_date":
            if not isinstance(data[field], str):
                raise ValueError("'event_date' must be a string.")
            value = data[field].strip()
            if not value:
                raise ValueError("'event_date' cannot be empty.")
            cleaned[field] = _validate_event_date(value)
        else:
            if not isinstance(data[field], str):
                raise ValueError(f"'{field}' must be a string.")
            value = data[field].strip()
            if field in REQUIRED_ACTIVITY_FIELDS and not value:
                raise ValueError(f"'{field}' cannot be empty.")
            max_len = ACTIVITY_FIELD_MAX_LENGTHS[field]
            if len(value) > max_len:
                raise ValueError(f"'{field}' must be at most {max_len} characters.")
            cleaned[field] = value

    if "event_date" in cleaned:
        _validate_event_date(cleaned["event_date"])
    for field, max_len in ACTIVITY_FIELD_MAX_LENGTHS.items():
        if field in cleaned and len(cleaned[field]) > max_len:
            raise ValueError(f"'{field}' must be at most {max_len} characters.")

    if is_update and not cleaned:
        raise ValueError("No valid activity fields provided for update.")

    return cleaned


def create_activity(db, ngo_id, data):
    """Create a new activity owned by an approved NGO."""
    _require_approved_ngo(db, ngo_id)
    cleaned = validate_activity_payload(data, is_update=False)
    now = _utc_now_iso()

    try:
        cursor = db.execute(
            """
            INSERT INTO activities (
                ngo_id, title, description, category, location,
                event_date, volunteers_needed, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ngo_id,
                cleaned["title"],
                cleaned["description"],
                cleaned.get("category", ""),
                cleaned["location"],
                cleaned["event_date"],
                cleaned.get("volunteers_needed", 1),
                cleaned.get("status", "open"),
                now,
                now,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise ConflictError("Activity could not be created due to a database constraint.") from exc
    except sqlite3.Error:
        db.rollback()
        raise

    return get_activity_by_id(db, cursor.lastrowid, ngo_id=ngo_id)


def list_activities_by_ngo(
    db, ngo_id, status=None, limit=DEFAULT_PAGE_LIMIT, offset=0
):
    """List activities belonging to an NGO with optional status filter and pagination."""
    clean_limit, clean_offset = _validate_pagination(limit, offset)
    query = f"SELECT {', '.join(ACTIVITY_COLUMNS)} FROM activities WHERE ngo_id = ?"
    params = [ngo_id]

    if status is not None:
        if not isinstance(status, str):
            raise ValueError("Invalid status filter. Status must be a string.")
        normalized_status = status.strip().lower()
        if normalized_status not in VALID_ACTIVITY_STATUSES:
            raise ValueError(
                f"Invalid status filter. Must be one of: {', '.join(sorted(VALID_ACTIVITY_STATUSES))}."
            )
        query += " AND status = ?"
        params.append(normalized_status)

    query += " ORDER BY event_date ASC, id DESC LIMIT ? OFFSET ?"
    params.extend([clean_limit, clean_offset])
    rows = db.execute(query, params).fetchall()
    return [_serialize_row(ACTIVITY_COLUMNS, row) for row in rows]


def get_activity_by_id(db, activity_id, ngo_id=None):
    """Fetch a single activity by ID, optionally scoped to an owning NGO."""
    query = f"SELECT {', '.join(ACTIVITY_COLUMNS)} FROM activities WHERE id = ?"
    params = [activity_id]

    if ngo_id is not None:
        query += " AND ngo_id = ?"
        params.append(ngo_id)

    row = db.execute(query, params).fetchone()
    return _serialize_row(ACTIVITY_COLUMNS, row)


def update_activity(db, activity_id, ngo_id, data):
    """Update an existing activity owned by `ngo_id`."""
    existing = get_activity_by_id(db, activity_id, ngo_id=ngo_id)
    if existing is None:
        raise LookupError("Activity not found for this NGO.")

    cleaned = validate_activity_payload(data, is_update=True)
    cleaned["updated_at"] = _utc_now_iso()

    assignments = ", ".join(f"{field} = ?" for field in cleaned)
    values = list(cleaned.values()) + [activity_id, ngo_id]

    try:
        db.execute(
            f"UPDATE activities SET {assignments} WHERE id = ? AND ngo_id = ?",
            values,
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise ConflictError("Activity could not be updated due to a database constraint.") from exc
    except sqlite3.Error:
        db.rollback()
        raise
    return get_activity_by_id(db, activity_id, ngo_id=ngo_id)


def delete_activity(db, activity_id, ngo_id):
    """Delete an activity owned by `ngo_id`."""
    existing = get_activity_by_id(db, activity_id, ngo_id=ngo_id)
    if existing is None:
        raise LookupError("Activity not found for this NGO.")

    try:
        db.execute(
            "DELETE FROM activities WHERE id = ? AND ngo_id = ?",
            (activity_id, ngo_id),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise ConflictError("Activity could not be deleted due to a database constraint.") from exc
    except sqlite3.Error:
        db.rollback()
        raise
    return existing


def list_requests_for_ngo(
    db, ngo_id, activity_id=None, status=None, limit=DEFAULT_PAGE_LIMIT, offset=0
):
    """List volunteer participation requests for activities owned by `ngo_id`."""
    clean_ngo_id = _parse_strict_int(ngo_id, "ngo_id", min_value=1)
    clean_limit, clean_offset = _validate_pagination(limit, offset)
    query = """
        SELECT
            pr.id,
            pr.activity_id,
            a.title AS activity_title,
            pr.volunteer_id,
            pr.message,
            pr.status,
            pr.reviewed_by,
            pr.reviewed_at,
            pr.created_at
        FROM participation_requests pr
        INNER JOIN activities a ON pr.activity_id = a.id
        WHERE a.ngo_id = ?
    """
    params = [clean_ngo_id]

    if activity_id is not None:
        clean_activity_id = _parse_strict_int(activity_id, "activity_id", min_value=1)
        query += " AND pr.activity_id = ?"
        params.append(clean_activity_id)

    if status is not None:
        if not isinstance(status, str):
            raise ValueError("Invalid request status filter. Status must be a string.")
        normalized_status = status.strip().lower()
        if normalized_status not in VALID_REQUEST_STATUSES:
            raise ValueError(
                f"Invalid request status filter. Must be one of: {', '.join(sorted(VALID_REQUEST_STATUSES))}."
            )
        query += " AND pr.status = ?"
        params.append(normalized_status)

    query += " ORDER BY pr.created_at DESC, pr.id DESC LIMIT ? OFFSET ?"
    params.extend([clean_limit, clean_offset])
    rows = db.execute(query, params).fetchall()
    return [_serialize_row(REQUEST_COLUMNS, row) for row in rows]


def _fetch_ngo_request(db, request_id, ngo_id):
    """Fetch a participation request scoped to an NGO along with activity state."""
    return db.execute(
        """
        SELECT
            pr.id,
            pr.activity_id,
            a.title AS activity_title,
            pr.volunteer_id,
            pr.message,
            pr.status,
            pr.reviewed_by,
            pr.reviewed_at,
            pr.created_at,
            a.status AS activity_status,
            a.volunteers_needed AS volunteers_needed
        FROM participation_requests pr
        INNER JOIN activities a ON pr.activity_id = a.id
        WHERE pr.id = ? AND a.ngo_id = ?
        """,
        (request_id, ngo_id),
    ).fetchone()


def review_participation_request(db, request_id, ngo_id, decision, reviewer_user_id):
    """Approve or reject a pending volunteer request for an approved NGO."""
    clean_request_id = _parse_strict_int(request_id, "request_id", min_value=1)
    clean_ngo_id = _parse_strict_int(ngo_id, "ngo_id", min_value=1)
    clean_reviewer_id = _parse_strict_int(reviewer_user_id, "reviewer_user_id", min_value=1)

    _require_approved_ngo(db, clean_ngo_id)

    if not isinstance(decision, str):
        raise ValueError("Decision must be 'approved' or 'rejected'.")
    normalized_decision = decision.strip().lower()
    if normalized_decision not in VALID_REVIEW_DECISIONS:
        raise ValueError("Decision must be 'approved' or 'rejected'.")

    row = _fetch_ngo_request(db, clean_request_id, clean_ngo_id)
    if row is None:
        raise LookupError("Participation request not found for this NGO.")

    request_record = _serialize_row(REQUEST_COLUMNS, row)
    activity_status = row["activity_status"] if isinstance(row, dict) else row[9]
    volunteers_needed = row["volunteers_needed"] if isinstance(row, dict) else row[10]

    if request_record["status"] != "pending":
        raise ConflictError(
            f"Participation request has already been processed (status: {request_record['status']})."
        )

    reviewed_at = _utc_now_iso()

    try:
        if normalized_decision == "approved":
            if activity_status != "open":
                raise ConflictError(
                    f"Cannot approve requests when activity status is '{activity_status}'."
                )

            # Atomic conditional update ensures concurrent approvals cannot exceed volunteers_needed.
            cursor = db.execute(
                """
                UPDATE participation_requests
                SET status = 'approved', reviewed_by = ?, reviewed_at = ?
                WHERE id = ?
                  AND status = 'pending'
                  AND (
                      SELECT COUNT(*)
                      FROM participation_requests
                      WHERE activity_id = ? AND status = 'approved'
                  ) < (
                      SELECT volunteers_needed
                      FROM activities
                      WHERE id = ? AND status = 'open'
                  )
                """,
                (
                    clean_reviewer_id,
                    reviewed_at,
                    clean_request_id,
                    request_record["activity_id"],
                    request_record["activity_id"],
                ),
            )
            if cursor.rowcount == 0:
                db.rollback()
                approved_row = db.execute(
                    "SELECT COUNT(*) FROM participation_requests WHERE activity_id = ? AND status = 'approved'",
                    (request_record["activity_id"],),
                ).fetchone()
                approved_count = (
                    approved_row[0]
                    if not isinstance(approved_row, dict)
                    else next(iter(approved_row.values()))
                )
                if approved_count >= volunteers_needed:
                    raise ConflictError(
                        "Volunteer capacity for this activity has already been reached."
                    )
                raise ConflictError(
                    "Participation request could not be approved due to a state conflict."
                )
        else:
            cursor = db.execute(
                """
                UPDATE participation_requests
                SET status = 'rejected', reviewed_by = ?, reviewed_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (clean_reviewer_id, reviewed_at, clean_request_id),
            )
            if cursor.rowcount == 0:
                db.rollback()
                raise ConflictError("Participation request has already been processed.")

        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise ConflictError("Participation request could not be updated due to a database constraint.") from exc
    except sqlite3.Error:
        db.rollback()
        raise

    request_record["status"] = normalized_decision
    request_record["reviewed_by"] = clean_reviewer_id
    request_record["reviewed_at"] = reviewed_at
    return request_record
