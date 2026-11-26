"""NGO data-access and validation module for Member 3.

Integration note:
    This module intentionally does NOT open its own SQLite connection or create
    tables at import time. Every database function expects Member 4's shared
    PEP 249 SQLite connection (`db`) to be passed in from the route layer.
"""

from datetime import datetime, timezone
import sqlite3
from urllib.parse import urlparse

NGO_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ngos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    organization_name TEXT NOT NULL,
    registration_number TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    email TEXT NOT NULL,
    phone TEXT DEFAULT '',
    address TEXT DEFAULT '',
    city TEXT DEFAULT '',
    website TEXT DEFAULT '',
    verification_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);
"""

NGO_COLUMNS = (
    "id",
    "user_id",
    "organization_name",
    "registration_number",
    "description",
    "email",
    "phone",
    "address",
    "city",
    "website",
    "verification_status",
    "created_at",
    "updated_at",
)

REQUIRED_NGO_FIELDS = ("organization_name", "registration_number", "email")

UPDATABLE_NGO_FIELDS = (
    "organization_name",
    "description",
    "email",
    "phone",
    "address",
    "city",
    "website",
)

NGO_FIELD_MAX_LENGTHS = {
    "organization_name": 150,
    "registration_number": 64,
    "description": 2000,
    "email": 254,
    "phone": 30,
    "address": 300,
    "city": 100,
    "website": 255,
}


class ConflictError(Exception):
    """Raised when an operation conflicts with existing resource state."""


def _utc_now_iso():
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _serialize_ngo(row):
    """Convert a database row matching NGO_COLUMNS into a dictionary."""
    if row is None:
        return None
    if isinstance(row, dict):
        return {col: row.get(col) for col in NGO_COLUMNS}
    return {col: row[idx] for idx, col in enumerate(NGO_COLUMNS)}


def _validate_email(email):
    """Perform basic email format and length validation."""
    if len(email) > NGO_FIELD_MAX_LENGTHS["email"] or "@" not in email:
        return False
    local, domain = email.rsplit("@", 1)
    return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".")


def _validate_website(url):
    """Allow only http:// or https:// URLs with a valid network location."""
    parsed = urlparse(url)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def validate_ngo_payload(data, is_update=False):
    """Validate and normalize NGO registration or profile update fields."""
    if not isinstance(data, dict):
        raise ValueError("Invalid NGO payload.")

    cleaned = {}
    if not is_update:
        for field in REQUIRED_NGO_FIELDS:
            raw = data.get(field)
            value = "" if raw is None else str(raw).strip()
            if not value:
                raise ValueError(f"'{field}' is required.")
            cleaned[field] = value

    candidate_fields = UPDATABLE_NGO_FIELDS if is_update else tuple(NGO_FIELD_MAX_LENGTHS.keys())

    for field in candidate_fields:
        if field not in data or data[field] is None:
            continue

        value = str(data[field]).strip()
        if field in REQUIRED_NGO_FIELDS and not value:
            raise ValueError(f"'{field}' cannot be empty.")

        max_len = NGO_FIELD_MAX_LENGTHS[field]
        if len(value) > max_len:
            raise ValueError(f"'{field}' must be at most {max_len} characters.")

        cleaned[field] = value

    if "email" in cleaned and not _validate_email(cleaned["email"]):
        raise ValueError("Please provide a valid email address.")

    if cleaned.get("website") and not _validate_website(cleaned["website"]):
        raise ValueError("'website' must start with http:// or https:// and include a valid host.")

    if is_update and not cleaned:
        raise ValueError("No valid profile fields provided for update.")

    return cleaned


def get_ngo_by_id(db, ngo_id):
    """Fetch a single NGO record by its primary key."""
    query = f"SELECT {', '.join(NGO_COLUMNS)} FROM ngos WHERE id = ?"
    row = db.execute(query, (ngo_id,)).fetchone()
    return _serialize_ngo(row)


def get_ngo_by_user_id(db, user_id):
    """Fetch the NGO profile associated with a Member 4 user_id."""
    query = f"SELECT {', '.join(NGO_COLUMNS)} FROM ngos WHERE user_id = ?"
    row = db.execute(query, (user_id,)).fetchone()
    return _serialize_ngo(row)


def create_ngo(db, user_id, data):
    """Create a new NGO profile linked to an existing authenticated user."""
    if get_ngo_by_user_id(db, user_id) is not None:
        raise ConflictError("An NGO profile already exists for this user.")

    cleaned = validate_ngo_payload(data, is_update=False)

    existing_reg = db.execute(
        "SELECT id FROM ngos WHERE registration_number = ?",
        (cleaned["registration_number"],),
    ).fetchone()
    if existing_reg is not None:
        raise ConflictError("An NGO with this registration number already exists.")

    now = _utc_now_iso()
    try:
        cursor = db.execute(
            """
            INSERT INTO ngos (
                user_id, organization_name, registration_number, description,
                email, phone, address, city, website, verification_status,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                user_id,
                cleaned["organization_name"],
                cleaned["registration_number"],
                cleaned.get("description", ""),
                cleaned["email"],
                cleaned.get("phone", ""),
                cleaned.get("address", ""),
                cleaned.get("city", ""),
                cleaned.get("website", ""),
                now,
                now,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise ConflictError("NGO profile conflicts with an existing record.") from exc

    return get_ngo_by_id(db, cursor.lastrowid)


def update_ngo_profile(db, ngo_id, data):
    """Update editable fields on an existing NGO profile."""
    existing = get_ngo_by_id(db, ngo_id)
    if existing is None:
        raise LookupError("NGO profile not found.")

    cleaned = validate_ngo_payload(data, is_update=True)
    cleaned["updated_at"] = _utc_now_iso()

    assignments = ", ".join(f"{field} = ?" for field in cleaned)
    values = list(cleaned.values()) + [ngo_id]

    db.execute(f"UPDATE ngos SET {assignments} WHERE id = ?", values)
    db.commit()
    return get_ngo_by_id(db, ngo_id)
