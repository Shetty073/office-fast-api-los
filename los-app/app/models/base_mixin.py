from datetime import datetime
from sqlalchemy import Column, DateTime

class TimestampMixin:
    """Provides automatic created_at and updated_at UTC timestamps on models."""
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
