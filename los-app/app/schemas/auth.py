from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class AppRegisterRequestSchema(BaseModel):
    username: str = Field(..., description="Unique client system or application username")
    password: str = Field(..., min_length=6, description="Client access secret / password")
    app_name: str = Field(..., description="Descriptive name of the client application (e.g. 'los_portal_ui')")
    is_admin: bool = Field(default=False, description="Whether this application has administrative permissions")
    enable_encryption: bool = Field(default=False, description="Enable request & response payload encryption")
    token_expiry_seconds: int = Field(default=86400, le=86400, ge=60, description="Custom JWT token expiration in seconds (max 86400)")

class AppRegisterResponseSchema(BaseModel):
    id: str
    username: str
    app_name: str
    is_admin: bool
    is_active: bool
    enable_encryption: bool
    encryption_key: Optional[str] = Field(None, description="Generated AES-256 base64 key (save securely, provided only on creation)")
    token_expiry_seconds: int
    created_at: datetime

    class Config:
        from_attributes = True

class LoginRequestSchema(BaseModel):
    username: str = Field(..., description="Client application or admin username")
    password: str = Field(..., description="Client password / secret")

class TokenResponseSchema(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    app_name: str
    enable_encryption: bool

class UserResponseSchema(BaseModel):
    id: str
    username: str
    app_name: str
    is_admin: bool
    is_active: bool
    enable_encryption: bool
    token_expiry_seconds: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class DeactivateUserResponseSchema(BaseModel):
    id: str
    username: str
    is_active: bool
    message: str
