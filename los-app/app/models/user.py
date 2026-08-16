from sqlalchemy import Column, Integer, String, Boolean
from app.db.base import Base
from app.models.base_mixin import TimestampMixin

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    app_name = Column(String(100), nullable=False, index=True)  # Name of client application / consumer
    hashed_password = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    enable_encryption = Column(Boolean, default=False, nullable=False)  # If True, payloads & responses are encrypted
    encryption_key = Column(String(255), nullable=True)  # Base64 encoded 256-bit AES key
    token_expiry_seconds = Column(Integer, default=86400, nullable=False)  # Custom JWT expiration in seconds (max 86400)
