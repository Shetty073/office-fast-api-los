import os
import socket
import logging
import re
import json
from contextvars import ContextVar
from typing import Any, Dict

# Context variables propagated per asynchronous request / task
request_id_ctx: ContextVar[str] = ContextVar("request_id_ctx", default="N/A")
client_app_ctx: ContextVar[str] = ContextVar("client_app_ctx", default="system")
username_ctx: ContextVar[str] = ContextVar("username_ctx", default="anonymous")

HOST_ID = os.getenv("CONTAINER_ID") or os.getenv("HOSTNAME") or socket.gethostname() or "unknown-host"

# Compiled regex patterns for PII data masking (DPDP Act compliance)
PII_PATTERNS = [
    # Mobile Number: 10 digit phone numbers (Indian & International standard)
    (re.compile(r'(?<!\d)(?:(?:\+91[\-\s]?)?[6-9]\d{9})(?!\d)'), '[MASKED_MOBILE]'),
    # Permanent Account Number (PAN): [A-Z]{5}[0-9]{4}[A-Z]
    (re.compile(r'\b[A-Z]{5}[0-9]{4}[A-Z]\b', re.IGNORECASE), '[MASKED_PAN]'),
    # Aadhaar Number: 12 digits (with or without spaces/dashes)
    (re.compile(r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b'), '[MASKED_AADHAAR]'),
    # Date of Birth: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY
    (re.compile(r'\b(?:\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4})\b'), '[MASKED_DOB]'),
    # Email addresses
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b'), '[MASKED_EMAIL]')
]

def mask_pii_string(text: str) -> str:
    """Recursively/iteratively sanitize text to mask all PII data."""
    if not text or not isinstance(text, str):
        return text
    sanitized = text
    for pattern, replacement in PII_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized

def mask_pii_data(data: Any) -> Any:
    """Mask PII in nested dictionaries, lists, or primitive types."""
    if isinstance(data, dict):
        return {k: mask_pii_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [mask_pii_data(item) for item in data]
    elif isinstance(data, str):
        return mask_pii_string(data)
    return data

class PIIMaskingLogFilter(logging.Filter):
    """Logging filter that redacts sensitive PII from log records."""
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_pii_string(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: mask_pii_string(v) if isinstance(v, str) else v for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(mask_pii_string(a) if isinstance(a, str) else a for a in record.args)
        return True

class ContextLogFormatter(logging.Formatter):
    """
    Structured context-aware log formatter.
    Injects timestamp, host/container ID, source system/app name, request ID,
    file name, function name, and line numbers.
    """
    def format(self, record: logging.LogRecord) -> str:
        req_id = request_id_ctx.get()
        app_name = client_app_ctx.get()
        user = username_ctx.get()
        
        # Inject standard contextual attributes
        record.host_id = HOST_ID
        record.request_id = req_id
        record.source_system = app_name
        record.user = user

        return super().format(record)

def setup_logger(logger_name: str = "los_app", log_level: str = "INFO") -> logging.Logger:
    """Configures and returns a contextual, PII-masked logger."""
    logger = logging.getLogger(logger_name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    if not logger.handlers:
        handler = logging.StreamHandler()
        log_format = (
            "[%(asctime)s] [%(levelname)s] [Host:%(host_id)s] [App:%(source_system)s] "
            "[ReqID:%(request_id)s] [%(filename)s:%(lineno)d (%(funcName)s)]: %(message)s"
        )
        formatter = ContextLogFormatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")
        handler.setFormatter(formatter)
        handler.addFilter(PIIMaskingLogFilter())
        logger.addHandler(handler)
        logger.propagate = False
        
    return logger

# Global application logger
logger = setup_logger("los_app")
