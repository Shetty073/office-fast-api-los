import uuid
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.user import User
from app.api.deps import get_current_user, get_current_admin_user
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    generate_aes_key
)
from app.schemas.auth import (
    AppRegisterRequestSchema,
    AppRegisterResponseSchema,
    LoginRequestSchema,
    TokenResponseSchema,
    UserResponseSchema,
    DeactivateUserResponseSchema
)
from app.core.logger import logger

router = APIRouter()

@router.post("/register-app", response_model=AppRegisterResponseSchema)
def register_application(
    payload: AppRegisterRequestSchema,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    Register a new client application / user. (Admin only)
    Configures whether encryption is enabled and custom token expiry (max 86400s).
    """
    existing_user = db.query(User).filter(User.username == payload.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Username '{payload.username}' is already registered."
        )

    encryption_key = None
    if payload.enable_encryption:
        encryption_key = generate_aes_key()

    new_user = User(
        id=str(uuid.uuid4()),
        username=payload.username,
        app_name=payload.app_name,
        hashed_password=get_password_hash(payload.password),
        is_admin=payload.is_admin,
        is_active=True,
        enable_encryption=payload.enable_encryption,
        encryption_key=encryption_key,
        token_expiry_seconds=payload.token_expiry_seconds
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    logger.info(f"Registered new client app: '{new_user.app_name}' (username: {new_user.username}) by admin {admin_user.username}")
    return new_user

@router.post("/login", response_model=TokenResponseSchema)
def login_for_access_token(
    payload: LoginRequestSchema,
    db: Session = Depends(get_db)
):
    """
    Authenticate user/application credentials and issue a signed JWT token.
    Token validity duration is configured per user (max 86400s).
    """
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        logger.warning(f"Failed login attempt for username: '{payload.username}'")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account has been deactivated."
        )

    expiry_delta = timedelta(seconds=user.token_expiry_seconds)
    access_token = create_access_token(
        subject=user.username,
        app_name=user.app_name,
        is_admin=user.is_admin,
        enable_encryption=user.enable_encryption,
        encryption_key=user.encryption_key,
        expires_delta=expiry_delta
    )

    logger.info(f"Generated JWT token for user '{user.username}' (app: '{user.app_name}') valid for {user.token_expiry_seconds}s")
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in_seconds": user.token_expiry_seconds,
        "app_name": user.app_name,
        "enable_encryption": user.enable_encryption
    }

@router.post("/deactivate/{user_id}", response_model=DeactivateUserResponseSchema)
def deactivate_application(
    user_id: str,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    Deactivate a client application / user account. (Admin only)
    """
    user = db.query(User).filter((User.id == user_id) | (User.username == user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if user.id == admin_user.id:
        raise HTTPException(status_code=400, detail="Admin cannot deactivate their own active account.")

    user.is_active = False
    db.commit()

    logger.info(f"Deactivated user '{user.username}' by admin '{admin_user.username}'")
    return {
        "id": user.id,
        "username": user.username,
        "is_active": False,
        "message": f"User '{user.username}' has been successfully deactivated."
    }

@router.get("/me", response_model=UserResponseSchema)
def get_current_user_profile(
    current_user: User = Depends(get_current_user)
):
    """Retrieve details of the currently authenticated user/app."""
    return current_user
