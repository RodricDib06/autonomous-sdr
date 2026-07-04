"""
Authentication router.

Endpoints:
    POST /auth/register          → create account (admin only after first user exists)
    POST /auth/login             → email + password → JWT pair
    POST /auth/refresh           → refresh_token → new access_token
    GET  /auth/me                → current user profile
    PUT  /auth/me/password       → change own password
    GET  /auth/users             → list all users (admin)
    PUT  /auth/users/{id}/role   → change a user's role (admin)
    DELETE /auth/users/{id}      → deactivate a user (admin)
    POST /auth/api-keys          → create API key (returns raw key once)
    GET  /auth/api-keys          → list own API keys
    DELETE /auth/api-keys/{id}   → revoke API key
"""

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, APIKeyHeader
from jose import JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.database.connection import get_db
from app.database.models import User, APIKey
from app.services.auth_service import (
    create_token,
    decode_token,
    generate_api_key,
    hash_password,
    verify_password,
)
from app.auth.dependencies import get_current_user, require_admin
from app.utils.time import utcnow
from app.schemas.auth import (
    AccessTokenResponse,
    APIKeyCreate,
    APIKeyCreatedResponse,
    APIKeyResponse,
    PasswordChange,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_bearer_optional = HTTPBearer(auto_error=False)
_api_key_optional = APIKeyHeader(name="X-API-Key", auto_error=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email.lower()).first()


def _build_token_response(user: User) -> TokenResponse:
    access = create_token(user.id, user.role, "access")
    refresh = create_token(user.id, user.role, "refresh")
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(user),
    )


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserCreate,
    db: Session = Depends(get_db),
    credentials: "HTTPAuthorizationCredentials | None" = Security(_bearer_optional),
    api_key_header: "str | None" = Security(_api_key_optional),
):
    """
    Create a new user account.
    - If no users exist yet: open registration (creates the first admin).
    - Otherwise: requires an existing admin to be authenticated.
    """
    from app.auth.dependencies import _user_from_jwt, _user_from_api_key

    is_first_user = db.query(User).count() == 0

    caller: User | None = None
    if not is_first_user:
        if credentials:
            caller = _user_from_jwt(credentials.credentials, db)
        if caller is None and api_key_header:
            caller = _user_from_api_key(api_key_header, db)
        if caller is None or caller.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Only admins can register new users",
                headers={"WWW-Authenticate": "Bearer"},
            )

    if _get_user_by_email(db, payload.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    # First user always becomes admin regardless of requested role
    role = "admin" if is_first_user else payload.role

    # Tenancy: first user lands in the default org; users registered by an
    # admin join that admin's org.
    from app.services.tenancy import get_default_org
    if caller is not None and caller.org_id:
        org_id = caller.org_id
    else:
        org_id = get_default_org(db).id

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        role=role,
        org_id=org_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return _build_token_response(user)


# ---------------------------------------------------------------------------
# Login / refresh
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = _get_user_by_email(db, payload.email)

    # Constant-time comparison path — don't reveal whether email exists
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled — contact your administrator",
        )

    user.last_login_at = utcnow()
    db.commit()

    return _build_token_response(user)


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh_token(payload: RefreshRequest, db: Session = Depends(get_db)):
    try:
        data = decode_token(payload.refresh_token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if data.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a refresh token")

    user = db.query(User).filter(User.id == data["sub"], User.is_active).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    access = create_token(user.id, user.role, "access")
    return AccessTokenResponse(
        access_token=access,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ---------------------------------------------------------------------------
# Current user profile
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    current_user.password_hash = hash_password(payload.new_password)
    db.commit()


# ---------------------------------------------------------------------------
# User management (admin only)
# ---------------------------------------------------------------------------

@router.get("/users", response_model=list[UserResponse])
def list_users(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return db.query(User).order_by(User.created_at).all()


@router.put("/users/{user_id}/role", response_model=UserResponse)
def change_user_role(
    user_id: str,
    role: str,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if role not in ("admin", "manager", "rep"):
        raise HTTPException(status_code=400, detail="Role must be admin, manager, or rep")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = role
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user(
    user_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    db.commit()


# ---------------------------------------------------------------------------
# API key management
# ---------------------------------------------------------------------------

@router.post("/api-keys", response_model=APIKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(
    payload: APIKeyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new API key. The raw key is returned ONCE — store it securely."""
    raw_key, prefix, key_hash = generate_api_key()

    api_key = APIKey(
        user_id=current_user.id,
        name=payload.name,
        key_prefix=prefix,
        key_hash=key_hash,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return APIKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        key=raw_key,
        key_prefix=prefix,
        created_at=api_key.created_at,
    )


@router.get("/api-keys", response_model=list[APIKeyResponse])
def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(APIKey)
        .filter(APIKey.user_id == current_user.id, APIKey.is_active)
        .order_by(APIKey.created_at.desc())
        .all()
    )


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    api_key = db.query(APIKey).filter(
        APIKey.id == key_id,
        APIKey.user_id == current_user.id,
    ).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    api_key.is_active = False
    db.commit()
