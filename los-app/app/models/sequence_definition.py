from sqlalchemy import Column, Integer, String, JSON, Text
from app.db.base import Base
from app.models.base_mixin import TimestampMixin

class SequenceDefinition(Base, TimestampMixin):
    __tablename__ = "sequence_definitions"

    id = Column(String(36), primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)
    sequence = Column(JSON, nullable=False)
    default_inputs = Column(JSON, nullable=True)
    mappings = Column(JSON, nullable=False, default=list)
    success_conditions = Column(JSON, nullable=True)
    conditions = Column(JSON, nullable=True)
