import os
import sqlite3
import sys
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash

import app as application

db_path = application.DB_PATH

if not os.path.isfile(db_path):
    print("ERROR: Database not found:", db_path)
    print("Start the application once to initialize its database, then rerun this script.")
    sys.exit(1)

email = "rugved0149@gmail.com"
username = "rugved0149"
password = "Rugved@29"
institution = "MITAOE Demo Campus"
timestamp = datetime.now(timezone.utc).isoformat()

# Refuse to continue if the database has no user table.
with sqlite3.connect(db_path) as db:
    tables = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    if "users" not in tables:
        print("ERROR: users table does not exist. No changes made.")
        sys.exit(1)

# Back up the database before changing account credentials.
backup_path = db_path + ".before_admin_bootstrap.bak"
source = sqlite3.connect(db_path)
backup = sqlite3.connect(backup_path)
try:
    source.backup(backup)
finally:
    backup.close()
    source.close()

db = sqlite3.connect(db_path)
db.row_factory = sqlite3.Row
try:
    columns = {r["name"] for r in db.execute("PRAGMA table_info(users)")}
    required = {"username", "password_hash", "role", "institution", "is_active"}
    if not required.issubset(columns):
        raise RuntimeError("Unexpected users schema; no account changes made.")

    matches = db.execute(
        "SELECT * FROM users WHERE lower(username)=lower(?) OR lower(email)=lower(?)"
        if "email" in columns else
        "SELECT * FROM users WHERE lower(username)=lower(?)",
        (username, email) if "email" in columns else (username,)
    ).fetchall()

    if len(matches) > 1:
        raise RuntimeError(
            "Username and email match different accounts. No changes made; resolve the duplicate manually."
        )

    values = {
        "username": username,
        "password_hash": generate_password_hash(password),
        "role": "institution_admin",
        "institution": institution,
        "is_active": 1,
    }
    if "email" in columns:
        values["email"] = email
    if "updated_at" in columns:
        values["updated_at"] = timestamp
    if "created_at" in columns and not matches:
        values["created_at"] = timestamp
    if "session_version" in columns:
        values["session_version"] = (
            (matches[0]["session_version"] or 0) + 1
            if matches and "session_version" in matches[0].keys()
            else 1
        )

    if matches:
        old_username = matches[0]["username"]
        # Avoid changing another user's username.
        collision = db.execute(
            "SELECT 1 FROM users WHERE lower(username)=lower(?) AND username<>?",
            (username, old_username)
        ).fetchone()
        if collision:
            raise RuntimeError("The requested username is already in use. No changes made.")

        assignments = ", ".join(f'"{key}"=?' for key in values)
        db.execute(
            f'UPDATE users SET {assignments} WHERE username=?',
            (*values.values(), old_username)
        )
        action = "Updated existing account"
    else:
        insert_values = {k: v for k, v in values.items() if k in columns}
        names = ", ".join(f'"{k}"' for k in insert_values)
        placeholders = ", ".join("?" for _ in insert_values)
        db.execute(
            f"INSERT INTO users ({names}) VALUES ({placeholders})",
            tuple(insert_values.values())
        )
        action = "Created account"

    db.commit()
    print(action + ":")
    print("Username:", username)
    print("Email:", email)
    print("Role: institution_admin")
    print("Active: yes")
    print("Database backup:", backup_path)
    print("Password stored as a hash; it was not printed.")
    print("Complete email OTP verification during first login if prompted.")
except Exception as exc:
    db.rollback()
    print("ERROR:", exc)
    print("Changes rolled back. Database backup:", backup_path)
    sys.exit(1)
finally:
    db.close()
