"""Password hashing (bcrypt) and JWT issue/verify.

We use the `bcrypt` library directly rather than passlib: passlib is unmaintained
(last release 2020) and breaks on modern bcrypt >= 5. bcrypt's own API is small
and stable. Note bcrypt hashes at most the first 72 bytes of the password, so we
truncate explicitly (the standard, documented approach).
"""
from __future__ import annotations

import datetime as dt

import bcrypt
from jose import JWTError, jwt

from ..config import settings

_MAX_BCRYPT_BYTES = 72


def _to_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_MAX_BCRYPT_BYTES]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_to_bytes(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str) -> str:
    expire = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    """Return the subject (user id as str) or None if the token is invalid/expired."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload.get("sub")
    except JWTError:
        return None
