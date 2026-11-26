
import os
import json
import re
from pathlib import Path

from flask import (
    Flask, request, jsonify, session, send_from_directory
)
from werkzeug.security import (
    generate_password_hash, check_password_hash
)

from database import get_db, init_db

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__)
app.secret_key = os.environ.get(
    "HH_SECRET_KEY", "change-this-development-secret"
)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax"
)


@app.get("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/api/health")
def health():
    return jsonify({
        "success": True,
        "message": "HelpingHands backend is running"
    })


@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}

    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    role = str(data.get("role", "")).lower()
    profile = data.get("profile", {})

    if not name or len(name) < 3:
        return jsonify(success=False, message="Enter a valid name"), 400

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return jsonify(success=False, message="Invalid email"), 400

    if len(password) < 6:
        return jsonify(success=False, message="Password must contain at least 6 characters"), 400

    if role not in ("volunteer", "donor", "ngo"):
        return jsonify(success=False, message="Invalid registration role"), 400

    if not isinstance(profile, dict):
        return jsonify(success=False, message="Invalid profile data"), 400

    conn = get_db()

    try:
        password_hash = generate_password_hash(password)
        status = "Pending" if role == "ngo" else "Active"

        cursor = conn.execute("""
            INSERT INTO users
            (name, email, password_hash, role, status, profile_json)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            name,
            email,
            password_hash,
            role,
            status,
            json.dumps(profile)
        ))

        conn.commit()

        return jsonify(
            success=True,
            message="Registration successful",
            status=status,
            user_id=cursor.lastrowid
        ), 201

    except Exception as error:
        if "UNIQUE constraint failed" in str(error):
            return jsonify(success=False, message="Email already registered"), 409
        app.logger.exception("Registration failed")
        return jsonify(success=False, message="Registration failed"), 500

    finally:
        conn.close()


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}

    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not email or not password:
        return jsonify(success=False, message="Email and password are required"), 400

    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE email = ?",
        (email,)
    ).fetchone()
    conn.close()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify(success=False, message="Invalid email or password"), 401

    if user["status"] == "Blocked":
        return jsonify(success=False, message="Account is blocked"), 403

    if user["status"] == "Pending":
        return jsonify(success=False, message="Account is waiting for admin approval"), 403

    session.clear()
    session["user_id"] = user["id"]
    session["role"] = user["role"]

    return jsonify(
        success=True,
        message="Login successful",
        user={
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"]
        }
    )


@app.get("/api/me")
def current_user():
    user_id = session.get("user_id")

    if not user_id:
        return jsonify(success=False, message="Not logged in"), 401

    conn = get_db()
    user = conn.execute(
        "SELECT id, name, email, role, status FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    conn.close()

    if not user:
        session.clear()
        return jsonify(success=False, message="User not found"), 401

    return jsonify(success=True, user=dict(user))


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(success=True, message="Logged out successfully")


# Serve existing frontend files without moving their folders.
@app.get("/<path:filename>")
def frontend_files(filename):
    return send_from_directory(BASE_DIR, filename)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
