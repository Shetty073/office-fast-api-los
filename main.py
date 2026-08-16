from fastapi import FastAPI
from contextlib import asynccontextmanager
from database import engine, Base
from routes import router
import services  # Imports package to execute registration decorators for all services
from redis_pool import init_redis_pool, close_redis_pool
import logging

logger = logging.getLogger(__name__)

# Automate DB table schema migrations/creations at startup
Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize ARQ Redis connection pool
    try:
        await init_redis_pool()
        logger.info("FastAPI connected to ARQ Redis pool successfully.")
    except Exception as e:
        logger.warning(f"Could not connect to Redis at startup: {e}")
    
    yield
    
    # Graceful shutdown of Redis connection pool
    await close_redis_pool()
    logger.info("FastAPI closed ARQ Redis pool.")

app = FastAPI(
    title="SCF LOS API Engine",
    description="Backend onboarding engine orchestrating standalone and chained third-party API calls.",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(router)

@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "SCF LOS Backend Engine is running successfully.",
        "registered_services": services.ServiceRegistry.list_services()
    }
