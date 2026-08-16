from datetime import datetime
from sqlalchemy import Column, Integer, String, JSON, Text, DateTime
from app.db.base import Base

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
