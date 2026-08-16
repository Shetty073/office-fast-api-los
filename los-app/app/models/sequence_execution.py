from datetime import datetime
from sqlalchemy import Column, Integer, String, JSON, DateTime
from app.db.base import Base

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

    @property
    def total_tasks(self) -> int:
        count = 0
        for item in (self.sequence or []):
            if isinstance(item, list):
                count += len(item)
            else:
                count += 1
        return count

    @property
    def completed_tasks(self) -> int:
        count = 0
        for step in (self.steps_data or []):
            if step.get("status") in ["COMPLETED", "SKIPPED"]:
                count += 1
        return count

    @property
    def pending_tasks(self) -> int:
        count = 0
        for step in (self.steps_data or []):
            if step.get("status") == "PENDING":
                count += 1
        remaining = self.total_tasks - len(self.steps_data or [])
        return max(0, count + remaining)

    @property
    def responses(self) -> dict:
        res = {}
        for step in (self.steps_data or []):
            s_name = step.get("service_name")
            if s_name and step.get("output_response") is not None:
                res[s_name] = step.get("output_response")
        return res
