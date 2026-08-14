from fastapi import FastAPI
from contextlib import asynccontextmanager
from database import engine, Base, SessionLocal
from routes import router
import services  # Imports package to execute registration decorators for all services
import asyncio
from models import SequenceExecution
from orchestrator import Orchestrator
import logging

logger = logging.getLogger(__name__)

# Automate DB table schema migrations/creations at startup
Base.metadata.create_all(bind=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup Recovery: Detect and resume pending/running executions that were interrupted.
    # To prevent race conditions in multi-instance deployments, we atomically claim tasks using a unique worker ID.
    import uuid
    worker_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        # Atomically claim any unclaimed PENDING or RUNNING task for this worker instance
        db.query(SequenceExecution).filter(
            SequenceExecution.status.in_(["PENDING", "RUNNING"]),
            (SequenceExecution.error_message == None) | (~SequenceExecution.error_message.like("Recovering:%"))
        ).update(
            {
                SequenceExecution.status: "PENDING",
                SequenceExecution.error_message: f"Recovering:{worker_id}"
            },
            synchronize_session=False
        )
        db.commit()

        # Query only the tasks successfully claimed by this worker
        claimed_runs = db.query(SequenceExecution).filter(
            SequenceExecution.error_message == f"Recovering:{worker_id}"
        ).all()

        if claimed_runs:
            logger.info(f"Startup: Worker {worker_id} claimed {len(claimed_runs)} interrupted sequence executions. Resuming...")
            for execution in claimed_runs:
                # Spawn non-blocking background task to resume execution.
                # error_message is kept as 'Recovering:{worker_id}' to serve as an active claim indicator.
                asyncio.create_task(Orchestrator.run_sequence(execution.id, lambda: SessionLocal()))
    except Exception as e:
        logger.error(f"Startup: Failed to recover interrupted tasks: {e}")
    finally:
        db.close()
    yield

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
