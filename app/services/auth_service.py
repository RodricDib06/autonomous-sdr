"""
Authentication service.

Handles password hashing, JWT creation/verification, and API key generation.
Nothing in this module touches the database — all DB operations live in the router.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Literal

import bcrypt
from jose import JWTError, jwt

from app.config import settings

# ---------------------------------------------------------------------------
# Password hashing (bcrypt direct — passlib 1.7.4 incompatible with bcrypt 4+)
# ---------------------------------------------------------------------------

import os as _os
_BCRYPT_ROUNDS = 4 if _os.getenv("TESTING") == "1" else 12


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(_BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
TokenType = Literal["access", "refresh"]


def create_token(
    subject: str,           # user id
    role: str,
    token_type: TokenType,
) -> str:
    if token_type == "access":
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    else:
        expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    payload = {
        "sub": subject,
        "role": role,
        "type": token_type,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT.  Raises jose.JWTError on any failure.
    Returns the raw payload dict — callers decide what to do with it.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
_API_KEY_PREFIX = "sdr_"
_RAW_KEY_BYTES = 32   # 32 bytes → 64 hex chars → total key: "sdr_" + 64 = 68 chars


def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key.

    Returns:
        (raw_key, key_prefix, key_hash)
        - raw_key:    full key shown to the user ONCE, e.g. "sdr_abc123..."
        - key_prefix: first 12 chars of raw_key for safe display later
        - key_hash:   SHA-256 hex digest stored in DB
    """
    raw = _API_KEY_PREFIX + secrets.token_hex(_RAW_KEY_BYTES)
    prefix = raw[:12]
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return raw, prefix, digest


def hash_api_key(raw_key: str) -> str:
    """Hash an incoming API key for DB lookup."""
    return hashlib.sha256(raw_key.encode()).hexdigest()
