
import os
import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_DIR = BASE_DIR / "database"
DB_PATH = DB_DIR / "helpinghands.db"


def get_db():
    DB_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Active',
            profile_json TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create initial admin account if it does not exist.
    admin_email = "admin@helpinghands.test"
    admin_password = os.environ.get(
        "HH_ADMIN_PASSWORD", "Admin@12345"
    )

    existing = conn.execute(
        "SELECT id FROM users WHERE email = ?",
        (admin_email,)
    ).fetchone()

    if not existing:
        conn.execute("""
            INSERT INTO users
            (name, email, password_hash, role, status)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "Admin User",
            admin_email,
            generate_password_hash(admin_password),
            "admin",
            "Active"
        ))

    conn.commit()
    conn.close()
