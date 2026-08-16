from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db.base import Base
from app.db.session import engine
from app.api.router import api_router
from app.services.registry import ServiceRegistry
from app.core.redis_pool import init_redis_pool, close_redis_pool
import app.services  # Auto-registers services
import logging

logger = logging.getLogger(__name__)

# Automate DB table schema migrations/creations at startup
Base.metadata.create_all(bind=engine)

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
    description="Backend onboarding engine orchestrating standalone and chained third-party API calls.",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(api_router, prefix="/api")

@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "SCF LOS Backend Engine is running successfully.",
        "registered_services": ServiceRegistry.list_services()
    }
