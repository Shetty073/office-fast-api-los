from sqlalchemy import Column, Integer, String, JSON
from app.db.base import Base
from app.models.base_mixin import TimestampMixin

class SequenceExecution(Base, TimestampMixin):
    __tablename__ = "sequence_executions"

    id = Column(String(36), primary_key=True, index=True)
    sequence_name = Column(String(100), nullable=True, index=True)
    sequence = Column(JSON, nullable=False)
    inputs = Column(JSON, nullable=False)
    trigger_payload = Column(JSON, nullable=True)
    mappings = Column(JSON, nullable=False)
    success_conditions = Column(JSON, nullable=True)
    idempotency_key = Column(String(100), nullable=True, unique=True, index=True)
    conditions = Column(JSON, nullable=True)
    context = Column(JSON, nullable=True)
    callback_url = Column(String(500), nullable=True)
    status = Column(String(20), default="PENDING")
    current_step = Column(Integer, default=0)
    steps_data = Column(JSON, default=list)
    error_message = Column(String(500), nullable=True)

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
