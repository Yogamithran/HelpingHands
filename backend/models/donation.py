"""Donation submission and tracking data-access module for Member 3.

Integration note:
    This module intentionally does NOT open its own SQLite connection or create
    tables at import time. Every database function expects Member 4's shared
    PEP 249 SQLite connection (`db`) to be passed in from the route layer.
"""

from datetime import datetime, timezone
import math
import sqlite3
import uuid

from backend.models.ngo import ConflictError

DONATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS donations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    donor_id INTEGER,
    donor_name TEXT NOT NULL,
    donor_email TEXT NOT NULL,
    ngo_id INTEGER NOT NULL,
    activity_id INTEGER,
    donation_type TEXT NOT NULL,
    amount REAL,
    item_description TEXT DEFAULT '',
    quantity INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    transaction_ref TEXT NOT NULL UNIQUE,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (donor_id) REFERENCES users (id) ON DELETE SET NULL,
    FOREIGN KEY (ngo_id) REFERENCES ngos (id) ON DELETE CASCADE,
    FOREIGN KEY (activity_id) REFERENCES activities (id) ON DELETE SET NULL
);
"""

DONATION_COLUMNS = (
    "id",
    "donor_id",
    "donor_name",
    "donor_email",
    "ngo_id",
    "ngo_name",
    "activity_id",
    "activity_title",
    "donation_type",
    "amount",
    "item_description",
    "quantity",
    "status",
    "transaction_ref",
    "notes",
    "created_at",
    "updated_at",
)

_DONATION_SELECT_SQL = """
SELECT
    d.id,
    d.donor_id,
    d.donor_name,
    d.donor_email,
    d.ngo_id,
    n.organization_name AS ngo_name,
    d.activity_id,
    a.title AS activity_title,
    d.donation_type,
    d.amount,
    d.item_description,
    d.quantity,
    d.status,
    d.transaction_ref,
    d.notes,
    d.created_at,
    d.updated_at
FROM donations d
INNER JOIN ngos n ON d.ngo_id = n.id
LEFT JOIN activities a ON d.activity_id = a.id
"""

VALID_DONATION_TYPES = frozenset({"monetary", "in_kind"})
VALID_DONATION_STATUSES = frozenset({"pending", "completed", "acknowledged", "cancelled"})

ALLOWED_STATUS_TRANSITIONS_BY_TYPE = {
    "monetary": {
        "pending": frozenset({"completed", "cancelled"}),
        "completed": frozenset({"acknowledged"}),
        "acknowledged": frozenset(),
        "cancelled": frozenset(),
    },
    "in_kind": {
        "pending": frozenset({"completed", "acknowledged", "cancelled"}),
        "completed": frozenset({"acknowledged"}),
        "acknowledged": frozenset(),
        "cancelled": frozenset(),
    },
}

DONATION_FIELD_MAX_LENGTHS = {
    "donor_name": 150,
    "donor_email": 254,
    "item_description": 500,
    "notes": 1000,
}

MAX_DONATION_AMOUNT = 10_000_000.00
MAX_DONATION_QUANTITY = 100_000
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100


def _utc_now_iso():
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _generate_transaction_ref():
    """Generate a unique internal donation tracking reference."""
    return f"HH-{uuid.uuid4().hex[:12].upper()}"


def _serialize_donation(row):
    """Map a database row matching DONATION_COLUMNS into a dictionary."""
    if row is None:
        return None
    if isinstance(row, dict):
        return {col: row.get(col) for col in DONATION_COLUMNS}
    return {col: row[idx] for idx, col in enumerate(DONATION_COLUMNS)}


def _validate_email(email):
    """Perform basic email format and length validation."""
    if len(email) > DONATION_FIELD_MAX_LENGTHS["donor_email"] or "@" not in email:
        return False
    local, domain = email.rsplit("@", 1)
    return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".")


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


def _validate_pagination(limit, offset):
    """Validate pagination limit and offset bounds."""
    clean_limit = _parse_strict_int(limit, "limit", min_value=1, max_value=MAX_PAGE_LIMIT)
    clean_offset = _parse_strict_int(offset, "offset", min_value=0)
    return clean_limit, clean_offset


def _require_string_field(data, field_name, required=True, max_length=None):
    """Extract and validate a string field from a payload dictionary."""
    raw = data.get(field_name)
    if raw is None:
        if required:
            raise ValueError(f"'{field_name}' is required.")
        return ""
    if not isinstance(raw, str):
        raise ValueError(f"'{field_name}' must be a string.")
    value = raw.strip()
    if required and not value:
        raise ValueError(f"'{field_name}' is required.")
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"'{field_name}' must be at most {max_length} characters.")
    return value


def validate_donation_payload(data):
    """Validate and normalize monetary or in-kind donation submission fields."""
    if not isinstance(data, dict):
        raise ValueError("Invalid donation payload.")

    donor_name = _require_string_field(
        data,
        "donor_name",
        required=True,
        max_length=DONATION_FIELD_MAX_LENGTHS["donor_name"],
    )
    donor_email = _require_string_field(
        data,
        "donor_email",
        required=True,
        max_length=DONATION_FIELD_MAX_LENGTHS["donor_email"],
    )
    if not _validate_email(donor_email):
        raise ValueError("Please provide a valid 'donor_email'.")

    if data.get("ngo_id") in (None, ""):
        raise ValueError("'ngo_id' is required.")
    ngo_id = _parse_strict_int(data["ngo_id"], "ngo_id", min_value=1)

    raw_activity_id = data.get("activity_id")
    activity_id = None
    if raw_activity_id not in (None, ""):
        activity_id = _parse_strict_int(raw_activity_id, "activity_id", min_value=1)

    donation_type = _require_string_field(
        data, "donation_type", required=True
    ).lower()
    if donation_type not in VALID_DONATION_TYPES:
        raise ValueError(
            f"'donation_type' must be one of: {', '.join(sorted(VALID_DONATION_TYPES))}."
        )

    amount = None
    item_description = ""
    quantity = None

    if donation_type == "monetary":
        raw_amount = data.get("amount")
        if raw_amount in (None, "") or isinstance(raw_amount, bool):
            raise ValueError("'amount' must be a valid positive number.")
        try:
            parsed_amount = float(raw_amount)
        except (TypeError, ValueError) as exc:
            raise ValueError("'amount' must be a valid number.") from exc
        if not math.isfinite(parsed_amount):
            raise ValueError("'amount' must be a finite number.")
        amount = round(parsed_amount, 2)
        if amount <= 0:
            raise ValueError("'amount' must be at least 0.01 after rounding.")
        if amount > MAX_DONATION_AMOUNT:
            raise ValueError(f"'amount' must be at most {MAX_DONATION_AMOUNT:.2f}.")
    else:
        item_description = _require_string_field(
            data,
            "item_description",
            required=True,
            max_length=DONATION_FIELD_MAX_LENGTHS["item_description"],
        )
        if data.get("quantity") in (None, ""):
            raise ValueError("'quantity' is required for in-kind donations.")
        quantity = _parse_strict_int(
            data["quantity"],
            "quantity",
            min_value=1,
            max_value=MAX_DONATION_QUANTITY,
        )

    notes = _require_string_field(
        data,
        "notes",
        required=False,
        max_length=DONATION_FIELD_MAX_LENGTHS["notes"],
    )

    return {
        "donor_name": donor_name,
        "donor_email": donor_email,
        "ngo_id": ngo_id,
        "activity_id": activity_id,
        "donation_type": donation_type,
        "amount": amount,
        "item_description": item_description,
        "quantity": quantity,
        "notes": notes,
    }


def _verify_ngo_and_activity(db, ngo_id, activity_id):
    """Ensure the target NGO exists and is approved, and optional activity belongs to it."""
    ngo_row = db.execute(
        "SELECT id, verification_status FROM ngos WHERE id = ?",
        (ngo_id,),
    ).fetchone()
    if ngo_row is None:
        raise LookupError("Target NGO not found.")

    verification_status = (
        ngo_row["verification_status"] if isinstance(ngo_row, dict) else ngo_row[1]
    )
    if verification_status != "approved":
        raise PermissionError(
            f"Target NGO is not approved to receive donations (status: {verification_status})."
        )

    if activity_id is not None:
        act_row = db.execute(
            "SELECT id, ngo_id FROM activities WHERE id = ?",
            (activity_id,),
        ).fetchone()
        if act_row is None:
            raise LookupError("Target activity not found.")
        act_ngo_id = act_row["ngo_id"] if isinstance(act_row, dict) else act_row[1]
        if act_ngo_id != ngo_id:
            raise ValueError("Selected activity does not belong to the specified NGO.")


def create_donation(db, data, donor_id=None):
    """Create a new monetary or in-kind donation linked to an approved NGO."""
    clean_donor_id = (
        None
        if donor_id is None
        else _parse_strict_int(donor_id, "donor_id", min_value=1)
    )
    cleaned = validate_donation_payload(data)
    _verify_ngo_and_activity(db, cleaned["ngo_id"], cleaned["activity_id"])

    now = _utc_now_iso()
    transaction_ref = _generate_transaction_ref()

    try:
        cursor = db.execute(
            """
            INSERT INTO donations (
                donor_id, donor_name, donor_email, ngo_id, activity_id,
                donation_type, amount, item_description, quantity,
                status, transaction_ref, notes, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (
                clean_donor_id,
                cleaned["donor_name"],
                cleaned["donor_email"],
                cleaned["ngo_id"],
                cleaned["activity_id"],
                cleaned["donation_type"],
                cleaned["amount"],
                cleaned["item_description"],
                cleaned["quantity"],
                transaction_ref,
                cleaned["notes"],
                now,
                now,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise ConflictError("Donation could not be recorded due to a conflict.") from exc
    except sqlite3.Error:
        db.rollback()
        raise

    return get_donation_by_id(db, cursor.lastrowid)


def get_donation_by_id(db, donation_id, donor_id=None, ngo_id=None):
    """Fetch a single donation, optionally scoped by donor_id or ngo_id."""
    clean_donation_id = _parse_strict_int(donation_id, "donation_id", min_value=1)
    query = f"{_DONATION_SELECT_SQL} WHERE d.id = ?"
    params = [clean_donation_id]

    if donor_id is not None:
        clean_donor_id = _parse_strict_int(donor_id, "donor_id", min_value=1)
        query += " AND d.donor_id = ?"
        params.append(clean_donor_id)

    if ngo_id is not None:
        clean_ngo_id = _parse_strict_int(ngo_id, "ngo_id", min_value=1)
        query += " AND d.ngo_id = ?"
        params.append(clean_ngo_id)

    row = db.execute(query, params).fetchone()
    return _serialize_donation(row)


def list_donations_by_donor(
    db, donor_id, status=None, limit=DEFAULT_PAGE_LIMIT, offset=0
):
    """List donations submitted by a specific donor with pagination."""
    clean_donor_id = _parse_strict_int(donor_id, "donor_id", min_value=1)
    clean_limit, clean_offset = _validate_pagination(limit, offset)
    query = f"{_DONATION_SELECT_SQL} WHERE d.donor_id = ?"
    params = [clean_donor_id]

    if status is not None:
        if not isinstance(status, str):
            raise ValueError("Invalid status filter. Status must be a string.")
        normalized_status = status.strip().lower()
        if normalized_status not in VALID_DONATION_STATUSES:
            raise ValueError(
                f"Invalid status filter. Must be one of: {', '.join(sorted(VALID_DONATION_STATUSES))}."
            )
        query += " AND d.status = ?"
        params.append(normalized_status)

    query += " ORDER BY d.created_at DESC, d.id DESC LIMIT ? OFFSET ?"
    params.extend([clean_limit, clean_offset])
    rows = db.execute(query, params).fetchall()
    return [_serialize_donation(row) for row in rows]


def list_donations_for_ngo(
    db, ngo_id, activity_id=None, status=None, limit=DEFAULT_PAGE_LIMIT, offset=0
):
    """List donations received by a specific NGO with pagination."""
    clean_ngo_id = _parse_strict_int(ngo_id, "ngo_id", min_value=1)
    clean_limit, clean_offset = _validate_pagination(limit, offset)
    query = f"{_DONATION_SELECT_SQL} WHERE d.ngo_id = ?"
    params = [clean_ngo_id]

    if activity_id is not None:
        clean_activity_id = _parse_strict_int(activity_id, "activity_id", min_value=1)
        query += " AND d.activity_id = ?"
        params.append(clean_activity_id)

    if status is not None:
        if not isinstance(status, str):
            raise ValueError("Invalid status filter. Status must be a string.")
        normalized_status = status.strip().lower()
        if normalized_status not in VALID_DONATION_STATUSES:
            raise ValueError(
                f"Invalid status filter. Must be one of: {', '.join(sorted(VALID_DONATION_STATUSES))}."
            )
        query += " AND d.status = ?"
        params.append(normalized_status)

    query += " ORDER BY d.created_at DESC, d.id DESC LIMIT ? OFFSET ?"
    params.extend([clean_limit, clean_offset])
    rows = db.execute(query, params).fetchall()
    return [_serialize_donation(row) for row in rows]


def update_donation_status_by_ngo(db, donation_id, ngo_id, new_status):
    """Update donation status for an NGO-owned donation following type-specific transitions."""
    clean_donation_id = _parse_strict_int(donation_id, "donation_id", min_value=1)
    clean_ngo_id = _parse_strict_int(ngo_id, "ngo_id", min_value=1)
    if not isinstance(new_status, str):
        raise ValueError("Invalid status. Status must be a string.")

    normalized_status = new_status.strip().lower()
    if normalized_status not in VALID_DONATION_STATUSES:
        raise ValueError(
            f"Invalid status. Must be one of: {', '.join(sorted(VALID_DONATION_STATUSES))}."
        )

    existing = get_donation_by_id(db, clean_donation_id, ngo_id=clean_ngo_id)
    if existing is None:
        raise LookupError("Donation not found for this NGO.")

    transitions_for_type = ALLOWED_STATUS_TRANSITIONS_BY_TYPE.get(existing["donation_type"], {})
    allowed_next = transitions_for_type.get(existing["status"], frozenset())
    if normalized_status not in allowed_next:
        raise ConflictError(
            f"Cannot transition {existing['donation_type']} donation from "
            f"'{existing['status']}' to '{normalized_status}'."
        )

    now = _utc_now_iso()
    try:
        cursor = db.execute(
            "UPDATE donations SET status = ?, updated_at = ? WHERE id = ? AND ngo_id = ? AND status = ?",
            (normalized_status, now, clean_donation_id, clean_ngo_id, existing["status"]),
        )
        if cursor.rowcount == 0:
            db.rollback()
            raise ConflictError("Donation status changed concurrently and could not be updated.")
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise ConflictError("Donation status could not be updated due to a constraint.") from exc
    except sqlite3.Error:
        db.rollback()
        raise

    return get_donation_by_id(db, clean_donation_id, ngo_id=clean_ngo_id)


def cancel_donation_by_donor(db, donation_id, donor_id):
    """Allow the submitting donor to cancel a donation while it is still pending."""
    clean_donation_id = _parse_strict_int(donation_id, "donation_id", min_value=1)
    clean_donor_id = _parse_strict_int(donor_id, "donor_id", min_value=1)

    existing = get_donation_by_id(db, clean_donation_id, donor_id=clean_donor_id)
    if existing is None:
        raise LookupError("Donation not found for this donor.")

    if existing["status"] != "pending":
        raise ConflictError(
            f"Only pending donations can be cancelled (current status: {existing['status']})."
        )

    now = _utc_now_iso()
    try:
        cursor = db.execute(
            "UPDATE donations SET status = 'cancelled', updated_at = ? WHERE id = ? AND donor_id = ? AND status = 'pending'",
            (now, clean_donation_id, clean_donor_id),
        )
        if cursor.rowcount == 0:
            db.rollback()
            raise ConflictError("Donation status changed concurrently and could not be cancelled.")
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise ConflictError("Donation could not be cancelled due to a constraint.") from exc
    except sqlite3.Error:
        db.rollback()
        raise

    return get_donation_by_id(db, clean_donation_id, donor_id=clean_donor_id)
