from dataclasses import dataclass
from functools import wraps
from flask import jsonify, g, session
from .db import get_db

@dataclass(frozen=True)
class Actor:
    user_id: str
    institution_id: str
    role: str

ALLOWED_ROLES = {"operator", "verifier", "institution_admin", "auditor"}

def require_actor(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            username = session.get("username")
            if not username:
                return jsonify({"error": "unauthorized", "message": "Sign in is required"}), 401
            user = get_db().execute(
                "SELECT username, role, institution, is_active FROM users WHERE username=?", (username,)
            ).fetchone()
            if not user or not user["is_active"] or not user["institution"]:
                return jsonify({"error": "unauthorized", "message": "Account has no institution membership"}), 401
            role = {"admin": "institution_admin"}.get(user["role"], user["role"])
            if role not in ALLOWED_ROLES:
                return jsonify({"error": "forbidden", "message": "Account role is not authorized"}), 403
            if roles and role not in roles:
                return jsonify({"error": "forbidden"}), 403
            g.actor = Actor(user["username"], user["institution"], role)
            return fn(*args, **kwargs)
        return wrapped
    return decorator
