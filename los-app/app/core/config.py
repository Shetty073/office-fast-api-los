import os

DATABASE_HOST = os.getenv("DB_HOST", "localhost")
DATABASE_PORT = os.getenv("DB_PORT", "5432")
DATABASE_USER = os.getenv("DB_USER", "postgres")
DATABASE_PASS = os.getenv("DB_PASS", "postgres")
DATABASE_NAME = os.getenv("DB_NAME", "office_proj")

POSTGRES_BASE_URL = f"postgresql+psycopg2://{DATABASE_USER}:{DATABASE_PASS}@{DATABASE_HOST}:{DATABASE_PORT}"
DATABASE_URL = os.getenv("DATABASE_URL", f"{POSTGRES_BASE_URL}/{DATABASE_NAME}")

# Redis Configuration for ARQ & Request Idempotency
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_DATABASE = int(os.getenv("REDIS_DATABASE", "0"))

FASTAPI_BASE_URL = os.getenv("FASTAPI_BASE_URL", "http://localhost:8000")

# Security & JWT Configurations
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "super-secret-production-key-change-in-env-32bytes")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
DEFAULT_TOKEN_EXPIRY_SECONDS = int(os.getenv("DEFAULT_TOKEN_EXPIRY_SECONDS", "86400"))
MAX_TOKEN_EXPIRY_SECONDS = 86400

# Request Deduplication / Idempotency Window in Milliseconds
IDEMPOTENCY_WINDOW_MS = int(os.getenv("IDEMPOTENCY_WINDOW_MS", "5000"))

# PII Masking Configuration
MASK_PII = os.getenv("MASK_PII", "true").lower() == "true"
