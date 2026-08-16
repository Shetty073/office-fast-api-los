from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db.base import Base
from app.db.session import engine, auto_migrate_columns
from app.api.router import api_router
from app.services.registry import ServiceRegistry
from app.core.redis_pool import init_redis_pool, close_redis_pool
from app.core.logger import setup_logger
from app.middleware import (
    RequestContextMiddleware,
    HashIdempotencyMiddleware,
    PayloadEncryptionMiddleware,
    AuditLoggingMiddleware
)
import app.services  # Auto-registers services

# Initialize structured, PII-masked logger
logger = setup_logger("los_app")

# Automate DB table schema migrations/creations at startup
Base.metadata.create_all(bind=engine)
auto_migrate_columns()

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_redis_pool()
        logger.info("FastAPI connected to ARQ Redis pool.")
    except Exception as e:
        logger.warning(f"Could not connect to Redis at startup: {e}")
    
    yield
    
    await close_redis_pool()
    logger.info("FastAPI closed ARQ Redis pool.")

app = FastAPI(
    title="SCF LOS API Engine",
    description="Enterprise-grade loan origination orchestration engine with authentication, PII masking, encryption, and request deduplication.",
    version="1.1.0",
    lifespan=lifespan
)

# In Starlette, add_middleware wraps in reverse order so the last added is executed FIRST on requests.
# Desired Request Pipeline: RequestContext -> Idempotency -> AuditLogging -> PayloadEncryption -> Router
# Outgoing Response Pipeline: Router -> PayloadEncryption (encrypts JSON) -> AuditLogging (captures final/encrypted) -> Idempotency -> RequestContext
app.add_middleware(PayloadEncryptionMiddleware)
app.add_middleware(AuditLoggingMiddleware)
app.add_middleware(HashIdempotencyMiddleware)
app.add_middleware(RequestContextMiddleware)

app.include_router(api_router, prefix="/api")

@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "SCF LOS Backend Engine is running successfully.",
        "registered_services": ServiceRegistry.list_services()
    }
