import os

DATABASE_HOST = os.getenv("DB_HOST", "localhost")
DATABASE_PORT = os.getenv("DB_PORT", "5432")
DATABASE_USER = os.getenv("DB_USER", "postgres")
DATABASE_PASS = os.getenv("DB_PASS", "postgres")
DATABASE_NAME = os.getenv("DB_NAME", "office_proj")

POSTGRES_BASE_URL = f"postgresql+psycopg2://{DATABASE_USER}:{DATABASE_PASS}@{DATABASE_HOST}:{DATABASE_PORT}"
DATABASE_URL = os.getenv("DATABASE_URL", f"{POSTGRES_BASE_URL}/{DATABASE_NAME}")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_DATABASE = int(os.getenv("REDIS_DATABASE", "0"))

FASTAPI_BASE_URL = os.getenv("FASTAPI_BASE_URL", "http://localhost:8000")

# Service Authentication Credentials for Orchestrator -> FastAPI dispatch
ORCHESTRATOR_AUTH_USERNAME = os.getenv("ORCHESTRATOR_AUTH_USERNAME", "admin")
ORCHESTRATOR_AUTH_PASSWORD = os.getenv("ORCHESTRATOR_AUTH_PASSWORD", "admin12345")
AUTH_TOKEN_CACHE_KEY = "los:orchestrator:jwt_token"
