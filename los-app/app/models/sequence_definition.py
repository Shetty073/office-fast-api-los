from datetime import datetime
from sqlalchemy import Column, Integer, String, JSON, Text, DateTime
from app.db.base import Base

class SequenceDefinition(Base):
    __tablename__ = "sequence_definitions"

    id = Column(String(36), primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)
    sequence = Column(JSON, nullable=False)  # List of service names (e.g. ["todo_service", ["post_service", "kyc_service"]])
    default_inputs = Column(JSON, nullable=True)  # Dict of default static inputs per service
    mappings = Column(JSON, nullable=False, default=list)  # List of dict mappings
    success_conditions = Column(JSON, nullable=True)  # Dict of success conditions per service
    conditions = Column(JSON, nullable=True)  # Dict of execution boolean expressions per service
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
