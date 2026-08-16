from sqlalchemy import Column, Integer, String, JSON, Text
from app.db.base import Base
from app.models.base_mixin import TimestampMixin

class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String(64), nullable=False, index=True)
    app_name = Column(String(100), nullable=True, index=True)
    username = Column(String(100), nullable=True, index=True)
    client_ip = Column(String(45), nullable=True)
    method = Column(String(10), nullable=False)
    path = Column(String(500), nullable=False, index=True)
    status_code = Column(Integer, nullable=False)
    duration_ms = Column(Integer, nullable=False)
    request_headers = Column(JSON, nullable=True)
    request_payload = Column(Text, nullable=True)  # Masked JSON/Text
    response_payload = Column(Text, nullable=True) # Masked JSON/Text
