from datetime import datetime
from sqlalchemy import Column, Integer, String, JSON, Text, DateTime
from database import Base

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

class SequenceExecution(Base):
    __tablename__ = "sequence_executions"

    id = Column(String(36), primary_key=True, index=True)
    sequence_name = Column(String(100), nullable=True, index=True)
    sequence = Column(JSON, nullable=False)  # List of service names
    inputs = Column(JSON, nullable=False)    # Dict of input payloads per service
    trigger_payload = Column(JSON, nullable=True)  # Raw trigger payload from client
    mappings = Column(JSON, nullable=False)  # List of dict mappings
    success_conditions = Column(JSON, nullable=True)  # Dict of success conditions per service
    idempotency_key = Column(String(100), nullable=True, unique=True, index=True)
    conditions = Column(JSON, nullable=True)  # Dict of execution conditions per service
    context = Column(JSON, nullable=True)  # Dict representing the shared global context
    callback_url = Column(String(500), nullable=True)  # Webhook URL for sequence outcomes
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
