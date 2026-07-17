"""
FastAPI dependency functions for authentication and role-based access control.

Usage:
    # Any authenticated user
    current_user: User = Depends(get_current_user)

    # Specific role requirement
    current_user: User = Depends(require_role("admin"))
    current_user: User = Depends(require_role("admin", "manager"))
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, APIKeyHeader
from jose import JWTError
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import User, APIKey
from app.services.auth_service import decode_token, hash_api_key
from app.utils.time import utcnow

# ---------------------------------------------------------------------------
# Security schemes
# ---------------------------------------------------------------------------
_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Role hierarchy — higher index = more privilege
_ROLE_LEVELS: dict[str, int] = {"rep": 1, "manager": 2, "admin": 3}

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired credentials",
    headers={"WWW-Authenticate": "Bearer"},
)
_INACTIVE_ERROR = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Account is disabled",
)


# ---------------------------------------------------------------------------
# Core identity resolution
# ---------------------------------------------------------------------------

def _user_from_jwt(token: str, db: Session) -> User | None:
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        user_id: str = payload.get("sub")
        if not user_id:
            return None
    except JWTError:
        return None

    return db.query(User).filter(User.id == user_id, User.is_active).first()


def _user_from_api_key(raw_key: str, db: Session) -> User | None:
    key_hash = hash_api_key(raw_key)
    api_key = (
        db.query(APIKey)
        .filter(APIKey.key_hash == key_hash, APIKey.is_active)
        .first()
    )
    if not api_key:
        return None

    # Touch last_used_at without a full commit round-trip
    api_key.last_used_at = utcnow()
    db.add(api_key)
    db.commit()

    return db.query(User).filter(User.id == api_key.user_id, User.is_active).first()


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    api_key: str | None = Security(_api_key_header),
    db: Session = Depends(get_db),
) -> User:
    """
    Resolve the caller's identity from either a Bearer JWT or an X-API-Key header.
    Raises 401 if neither is present or valid.
    """
    user: User | None = None

    if credentials:
        user = _user_from_jwt(credentials.credentials, db)

    if user is None and api_key:
        user = _user_from_api_key(api_key, db)

    if user is None:
        raise _CREDENTIALS_ERROR

    if not user.is_active:
        raise _INACTIVE_ERROR

    # Read-only demo accounts (DEMO_READONLY_EMAILS): browse everything,
    # mutate nothing — safe to publish the login in the README
    from app.config import settings
    if (
        user.email.lower() in settings.demo_readonly_emails
        and request.method not in ("GET", "HEAD", "OPTIONS")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This is a read-only demo account — mutations are disabled.",
        )

    return user


# ---------------------------------------------------------------------------
# Role-based guards
# ---------------------------------------------------------------------------

def require_role(*roles: str):
    """
    Returns a FastAPI dependency that enforces one of the given roles.

    Example:
        Depends(require_role("admin"))
        Depends(require_role("admin", "manager"))
    """
    min_level = min(_ROLE_LEVELS.get(r, 0) for r in roles)

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        user_level = _ROLE_LEVELS.get(current_user.role, 0)
        if user_level < min_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of: {', '.join(roles)}",
            )
        return current_user

    return dependency


# Convenience aliases used throughout the codebase
require_admin = require_role("admin")
require_manager = require_role("admin", "manager")
require_rep = require_role("admin", "manager", "rep")   # any authenticated user
