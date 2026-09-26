"""JWT authentication: token creation plus the login_required / admin_required decorators."""
import datetime as dt
from functools import wraps

import jwt
from flask import current_app, g, request

from db import get_db
from helpers import error


def create_token(user_id, role):
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + dt.timedelta(hours=current_app.config["TOKEN_HOURS"]),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def login_required(fn):
    """Reject the request unless it carries a valid 'Authorization: Bearer <token>' header.

    On success the user row is available as flask.g.user. The user is re-read from the
    database on every request, so a deleted user's old token stops working immediately.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return error("Sign in to continue", 401)
        try:
            payload = jwt.decode(header[7:], current_app.config["SECRET_KEY"], algorithms=["HS256"])
            user_id = int(payload["sub"])
        except jwt.ExpiredSignatureError:
            return error("Your session expired. Sign in again", 401)
        except (jwt.InvalidTokenError, KeyError, ValueError):
            return error("Invalid token", 401)

        user = get_db().execute(
            "SELECT id, name, email, role FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if user is None:
            return error("Account not found", 401)
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    """Like login_required, but the user must also have the 'admin' role (403 otherwise)."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if g.user["role"] != "admin":
            return error("Admin access required", 403)
        return fn(*args, **kwargs)

    return login_required(wrapper)
