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


def user_from_query_token(token: str | None, db: Session) -> User:
    """
    Authenticate an SSE request. EventSource can't set headers, so the JWT
    rides in ?token= — and a missing token must fail like a bad one, or
    dropping the parameter would bypass auth entirely.
    """
    user = _user_from_jwt(token, db) if token else None
    if user is None:
        raise _CREDENTIALS_ERROR
    return user


def _identify(request: Request, db: Session) -> User | None:
    """Best-effort caller lookup from any credential the request carries."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        user = _user_from_jwt(auth[7:], db)
        if user:
            return user
    api_key = request.headers.get("x-api-key")
    if api_key:
        user = _user_from_api_key(api_key, db)
        if user:
            return user
    token = request.query_params.get("token")
    if token:
        return _user_from_jwt(token, db)
    return None


def _org_of(db: Session, param: str, value: str):
    """(found, org_id) for the record a path parameter names."""
    from app.database.models import BookingRequest, Conversation, Lead, OutreachEmail

    if param in ("lead_id", "primary_id", "duplicate_id"):
        row = db.query(Lead.org_id).filter(Lead.id == value).first()
    else:
        child = {
            "email_id": OutreachEmail,
            "conv_id": Conversation,
            "booking_id": BookingRequest,
        }[param]
        row = (
            db.query(Lead.org_id)
            .join(child, child.lead_id == Lead.id)
            .filter(child.id == value)
            .first()
        )
    return (row is not None, row[0] if row else None)


_ORG_GUARDED_PATH_PARAMS = ("lead_id", "primary_id", "duplicate_id", "email_id", "conv_id", "booking_id")


def enforce_path_org(request: Request, db: Session = Depends(get_db)) -> None:
    """
    App-wide guard: any route whose path names a lead (or a record hanging off
    one) answers 404 when that record belongs to another organization.

    Registered once on the app instead of per handler, so a new
    /leads/{lead_id}/... route is tenant-safe without remembering to be.
    Unknown ids pass through to the handler's own 404, and anonymous callers
    pass through to the handler's own auth — this only ever narrows access.
    """
    params = [p for p in _ORG_GUARDED_PATH_PARAMS if p in request.path_params]
    if not params:
        return
    user = _identify(request, db)
    if user is None or user.org_id is None:
        return
    for param in params:
        found, org_id = _org_of(db, param, request.path_params[param])
        if found and org_id != user.org_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


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


def require_instance_admin(current_user: User = Depends(require_role("admin"))) -> User:
    """Admin of the operator's org — for settings shared by every tenant."""
    from app.services.tenancy import is_instance_admin
    if not is_instance_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Instance-wide settings can only be changed by the operator's admins",
        )
    return current_user


# Convenience aliases used throughout the codebase
require_admin = require_role("admin")
require_manager = require_role("admin", "manager")
require_rep = require_role("admin", "manager", "rep")   # any authenticated user
