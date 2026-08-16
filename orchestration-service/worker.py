import asyncio
import logging
import httpx
from typing import Dict, Any, List, Tuple
from arq.connections import RedisSettings
import config
from database import get_db
from models import SequenceExecution
from orchestrator import Orchestrator

logger = logging.getLogger(__name__)

async def run_sequence_task(ctx: Dict[str, Any], execution_id: str):
    """
    ARQ worker task entry point for executing an orchestration sequence.
    Dispatches generic HTTP calls to FastAPI.
    """
    logger.info(f"ARQ Worker: Starting sequence task for execution_id={execution_id}")
    await Orchestrator.run_sequence(execution_id, lambda: get_db())
    logger.info(f"ARQ Worker: Completed sequence task for execution_id={execution_id}")

async def rollback_sequence_task(ctx: Dict[str, Any], execution_id: str, completed_steps: List[Tuple[str, Dict[str, Any], Dict[str, Any]]]):
    """
    ARQ worker task entry point for executing Saga rollback compensation transactions.
    """
    logger.info(f"ARQ Worker: Starting manual rollback task for execution_id={execution_id}")
    async with httpx.AsyncClient(timeout=15.0) as client:
        for name, payload, response in reversed(completed_steps):
            compensate_url = f"{config.FASTAPI_BASE_URL.rstrip('/')}/api/standalone/{name}/compensate"
            try:
                logger.info(f"ARQ SAGA: Calling compensation for '{name}' at {compensate_url}")
                await client.post(
                    compensate_url,
                    json={"input_payload": payload, "output_response": response},
                    headers={"X-Execution-Id": execution_id}
                )
            except Exception as e:
                logger.error(f"ARQ SAGA: Compensating transaction failed for service '{name}': {e}")

async def startup(ctx: Dict[str, Any]):
    logger.info("ARQ Orchestration Worker starting up...")

async def shutdown(ctx: Dict[str, Any]):
    logger.info("ARQ Orchestration Worker shutting down...")

class WorkerSettings:
    functions = [run_sequence_task, rollback_sequence_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings(
        host=config.REDIS_HOST,
        port=config.REDIS_PORT,
        password=config.REDIS_PASSWORD,
        database=config.REDIS_DATABASE
    )
    max_jobs = 20
    job_timeout = 600
