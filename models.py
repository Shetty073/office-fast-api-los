from datetime import datetime
from sqlalchemy import Column, Integer, String, JSON, Text, DateTime
from database import Base

class SequenceExecution(Base):
    __tablename__ = "sequence_executions"

    id = Column(String(36), primary_key=True, index=True)
    sequence = Column(JSON, nullable=False)  # List of service names
    inputs = Column(JSON, nullable=False)    # Dict of input payloads per service
    mappings = Column(JSON, nullable=False)  # List of dict mappings
    status = Column(String(20), default="PENDING")  # PENDING, RUNNING, COMPLETED, PARTIAL_SUCCESS, FAILED
    current_step = Column(Integer, default=0)
    steps_data = Column(JSON, default=list)  # Step tracking (JSON serialization)
    error_message = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class APILog(Base):
    __tablename__ = "api_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(String(36), nullable=True, index=True)
    service_name = Column(String(100), nullable=False, index=True)
    method = Column(String(10), nullable=False)
    url = Column(String(500), nullable=False)
    request_headers = Column(JSON, nullable=True)
    request_body = Column(Text, nullable=True)
    response_status = Column(Integer, nullable=True)
    response_headers = Column(JSON, nullable=True)
    response_body = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
