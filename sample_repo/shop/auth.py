"""User accounts, password hashing and sessions."""

import hashlib
import hmac
import os
import secrets
import time

from shop import db

SESSION_LIFETIME_SECONDS = 60 * 60 * 24
PBKDF2_ROUNDS = 200_000

_sessions = {}


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return salt.hex() + ":" + digest.hex()


def verify_password(password: str, stored_hash: str) -> bool:
    salt_hex, digest_hex = stored_hash.split(":")
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return hmac.compare_digest(digest.hex(), digest_hex)


def register_user(connection, email: str, password: str) -> int:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    return db.execute(
        connection,
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        (email.lower(), hash_password(password)),
    )


def find_user_by_email(connection, email: str):
    return db.fetch_one(connection, "SELECT * FROM users WHERE email = ?", (email.lower(),))


def login(connection, email: str, password: str) -> str | None:
    user = find_user_by_email(connection, email)
    if user is None:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    token = secrets.token_urlsafe(32)
    _sessions[token] = {"user_id": user["id"], "expires_at": time.time() + SESSION_LIFETIME_SECONDS}
    return token


def get_session_user_id(token: str) -> int | None:
    session = _sessions.get(token)
    if session is None:
        return None
    if session["expires_at"] < time.time():
        del _sessions[token]
        return None
    return session["user_id"]


def require_admin(connection, token: str) -> int:
    user_id = get_session_user_id(token)
    if user_id is None:
        raise PermissionError("Not logged in")
    user = db.fetch_one(connection, "SELECT is_admin FROM users WHERE id = ?", (user_id,))
    if user is None or not user["is_admin"]:
        raise PermissionError("Admin only")
    return user_id
