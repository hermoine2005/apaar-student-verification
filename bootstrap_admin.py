"""Safely create an institution administrator without embedded credentials.

Usage:
  python bootstrap_admin.py
  python bootstrap_admin.py --update-existing

Configuration may be supplied through APAAR_BOOTSTRAP_USERNAME,
APAAR_BOOTSTRAP_EMAIL, APAAR_BOOTSTRAP_INSTITUTION, and
APAAR_BOOTSTRAP_PASSWORD. Password input is hidden when prompted.
"""
import argparse
import getpass
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from werkzeug.security import generate_password_hash

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get(
    "APAAR_DB_PATH", str(APP_DIR / "instance" / "apaar_demo.db")
))


def prompt_value(env_name, label, *, default=""):
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    suffix = f" [{default}]" if default else ""
    answer = input(f"{label}{suffix}: ").strip()
    return answer or default


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="explicitly allow resetting credentials for a matching account",
    )
    args = parser.parse_args()

    if not DB_PATH.is_file():
        print(f"ERROR: Database not found: {DB_PATH}", file=sys.stderr)
        print("Start the application once to initialize the database, then retry.", file=sys.stderr)
        return 1

    username = prompt_value("APAAR_BOOTSTRAP_USERNAME", "Administrator username")
    email = prompt_value("APAAR_BOOTSTRAP_EMAIL", "Administrator email (optional)")
    institution = prompt_value(
        "APAAR_BOOTSTRAP_INSTITUTION", "Institution name", default="MITAOE Demo Campus"
    )
    password = os.environ.get("APAAR_BOOTSTRAP_PASSWORD", "")
    if not password:
        password = getpass.getpass("New administrator password (input hidden): ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            print("ERROR: Passwords do not match; no changes made.", file=sys.stderr)
            return 1

    if not username or len(username) > 40:
        print("ERROR: Username is required and must be at most 40 characters.", file=sys.stderr)
        return 1
    if not institution or len(institution) > 160:
        print("ERROR: Institution is required and must be at most 160 characters.", file=sys.stderr)
        return 1
    if len(password) < 16:
        print("ERROR: Use a password of at least 16 characters.", file=sys.stderr)
        return 1
    if email and (len(email) > 254 or "@" not in email):
        print("ERROR: Email address appears invalid.", file=sys.stderr)
        return 1

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "users" not in tables:
            print("ERROR: users table does not exist; no changes made.", file=sys.stderr)
            return 1

        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        required = {"username", "password_hash", "role", "institution", "is_active"}
        if not required.issubset(columns):
            print("ERROR: Unexpected users schema; no changes made.", file=sys.stderr)
            return 1

        clauses = ["lower(username)=lower(?)"]
        params = [username]
        if email and "email" in columns:
            clauses.append("lower(email)=lower(?)")
            params.append(email)
        matches = db.execute(
            "SELECT * FROM users WHERE " + " OR ".join(clauses), params
        ).fetchall()
        if len(matches) > 1:
            print("ERROR: Username/email match different accounts; resolve manually.", file=sys.stderr)
            return 1
        if matches and not args.update_existing:
            print(
                "ERROR: A matching account already exists. No changes made. "
                "Use --update-existing only if you intend to reset it.",
                file=sys.stderr,
            )
            return 1

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = DB_PATH.with_name(f"{DB_PATH.name}.admin-bootstrap-{stamp}.bak")
        source = sqlite3.connect(DB_PATH)
        backup = sqlite3.connect(backup_path)
        try:
            source.backup(backup)
        finally:
            backup.close()
            source.close()

        values = {
            "username": username,
            "password_hash": generate_password_hash(password),
            "role": "institution_admin",
            "institution": institution,
            "is_active": 1,
        }
        if "email" in columns:
            values["email"] = email or None
        if "updated_at" in columns:
            values["updated_at"] = timestamp
        if "created_at" in columns and not matches:
            values["created_at"] = timestamp
        if "session_version" in columns:
            values["session_version"] = (
                int(matches[0]["session_version"] or 0) + 1
                if matches and "session_version" in matches[0].keys()
                else 1
            )

        try:
            if matches:
                assignments = ", ".join(f'"{key}"=?' for key in values)
                db.execute(
                    f'UPDATE users SET {assignments} WHERE id=?',
                    (*values.values(), matches[0]["id"]),
                )
                action = "Updated existing administrator account"
            else:
                insert_values = {key: value for key, value in values.items() if key in columns}
                names = ", ".join(f'"{key}"' for key in insert_values)
                placeholders = ", ".join("?" for _ in insert_values)
                db.execute(
                    f"INSERT INTO users ({names}) VALUES ({placeholders})",
                    tuple(insert_values.values()),
                )
                action = "Created administrator account"
            db.commit()
        except Exception:
            db.rollback()
            raise

    print(action)
    print(f"Username: {username}")
    print(f"Institution: {institution}")
    print("Password was stored as a hash and was not printed.")
    print(f"Database backup: {backup_path}")
    print("Remove APAAR_BOOTSTRAP_PASSWORD from the environment if you set it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
