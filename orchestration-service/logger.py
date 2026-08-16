import os
import socket
import logging
import re
from typing import Any

HOST_ID = os.getenv("CONTAINER_ID") or os.getenv("HOSTNAME") or socket.gethostname() or "unknown-host"

# Compiled regex patterns for PII data masking (DPDP Act compliance)
PII_PATTERNS = [
    (re.compile(r'(?<!\d)(?:(?:\+91[\-\s]?)?[6-9]\d{9})(?!\d)'), '[MASKED_MOBILE]'),
    (re.compile(r'\b[A-Z]{5}[0-9]{4}[A-Z]\b', re.IGNORECASE), '[MASKED_PAN]'),
    (re.compile(r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b'), '[MASKED_AADHAAR]'),
    (re.compile(r'\b(?:\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4})\b'), '[MASKED_DOB]'),
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b'), '[MASKED_EMAIL]')
]

def mask_pii_string(text: str) -> str:
    if not text or not isinstance(text, str):
        return text
    sanitized = text
    for pattern, replacement in PII_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized

class PIIMaskingLogFilter(logging.Filter):
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
    def format(self, record: logging.LogRecord) -> str:
        record.host_id = HOST_ID
        return super().format(record)

def setup_worker_logger(log_level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("arq_worker")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    if not logger.handlers:
        handler = logging.StreamHandler()
        log_format = (
            "[%(asctime)s] [%(levelname)s] [Host:%(host_id)s] [Worker] "
            "[%(filename)s:%(lineno)d (%(funcName)s)]: %(message)s"
        )
        formatter = ContextLogFormatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")
        handler.setFormatter(formatter)
        handler.addFilter(PIIMaskingLogFilter())
        logger.addHandler(handler)
        logger.propagate = False
        
    return logger

logger = setup_worker_logger()
