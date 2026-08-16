from fastapi import APIRouter, Depends, HTTPException, Query, Header, Request
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional, List
from arq.jobs import Job
from database import get_db
from models import SequenceExecution, SequenceDefinition
from services.registry import ServiceRegistry
from sequence_manager import SequenceManager
from schemas import (
    SequenceTriggerSchema, 
    SequenceExecutionResponseSchema, 
    SequenceRetrySchema,
    SequenceDefinitionCreateSchema,
    SequenceDefinitionResponseSchema,
    TriggerSequencePayloadSchema
)
from redis_pool import get_arq_redis
from utils import APIClient
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# ==========================================
# 1. STANDALONE & COMPENSATION SERVICE APIS
# ==========================================

@router.post("/standalone/{service_name}")
async def call_standalone(
    service_name: str, 
    payload: Dict[str, Any], 
    mock: Optional[bool] = Query(None, description="Force enable/disable mock for this execution"),
    x_execution_source: Optional[str] = Header(default="standalone", alias="X-Execution-Source"),
    x_execution_id: Optional[str] = Header(default=None, alias="X-Execution-Id")
):
    """
    1st Endpoint: Standalone dynamic API call.
    Finds the service from the registry by its name, executes it, and returns the standard response.
    Identifies whether called standalone by user or by the ARQ orchestrator via X-Execution-Source header.
    """
    try:
        service = ServiceRegistry.get(service_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found.")

    result = await service.execute(
        payload=payload, 
        execution_id=x_execution_id,
        mock_override=mock,
        execution_source=x_execution_source
    )
    
    if not result.get("success"):
        raise HTTPException(
            status_code=result.get("status_code", 400), 
            detail=result.get("error", "Service failed during execution.")
        )
        
    return result

@router.post("/standalone/{service_name}/compensate")
async def call_compensate(
    service_name: str,
    payload: Dict[str, Any],
    x_execution_id: Optional[str] = Header(default=None, alias="X-Execution-Id")
):
    """
    Generic Saga compensation endpoint invoked during rollbacks.
    """
    try:
        service = ServiceRegistry.get(service_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found.")

    client = APIClient(service_name=service.name, execution_id=x_execution_id, timeout=service.timeout)
    input_payload = payload.get("input_payload", {})
    output_response = payload.get("output_response", {})
    
    await service.compensate(payload=input_payload, response=output_response, client=client)
    return {"status": "compensated", "service": service_name}

# ==========================================
# 2. SEQUENCE DEFINITION RECIPES (DB-DRIVEN)
# ==========================================

@router.post("/sequences", response_model=SequenceDefinitionResponseSchema)
def create_or_update_sequence_definition(
    payload: SequenceDefinitionCreateSchema,
    db: Session = Depends(get_db)
):
    """
    Register or update a sequence definition recipe in the database.
    Allows developers to configure new sequences without touching orchestrator code.
    """
    try:
        seq_def = SequenceManager.create_definition(
            db=db,
            name=payload.name,
            sequence=payload.sequence,
            description=payload.description,
            default_inputs=payload.default_inputs,
            mappings=payload.mappings,
            success_conditions=payload.success_conditions,
            conditions=payload.conditions
        )
        return seq_def
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/sequences", response_model=List[SequenceDefinitionResponseSchema])
def list_sequence_definitions(db: Session = Depends(get_db)):
    """List all registered sequence recipes stored in the database."""
    return db.query(SequenceDefinition).all()

@router.get("/sequences/{name_or_id}", response_model=SequenceDefinitionResponseSchema)
def get_sequence_definition(name_or_id: str, db: Session = Depends(get_db)):
    """Retrieve a specific sequence recipe by its name or ID."""
    seq_def = db.query(SequenceDefinition).filter(
        (SequenceDefinition.name == name_or_id) | (SequenceDefinition.id == name_or_id)
    ).first()
    if not seq_def:
        raise HTTPException(status_code=404, detail=f"Sequence definition '{name_or_id}' not found.")
    return seq_def

# ==========================================
# 3. TRIGGER, STATUS, CANCEL & RETRY APIS
# ==========================================

@router.post("/chain/trigger/{sequence_name_or_id}", response_model=SequenceExecutionResponseSchema)
async def trigger_by_sequence_name(
    sequence_name_or_id: str,
    payload: TriggerSequencePayloadSchema,
    db: Session = Depends(get_db)
):
    """
    Trigger a named sequence recipe.
    Fetches the configuration from DB, initializes the execution record, and enqueues to ARQ.
    """
    try:
        execution = SequenceManager.trigger_by_definition(
            db=db,
            sequence_name_or_id=sequence_name_or_id,
            trigger_payload=payload.payload,
            inputs_override=payload.inputs_override,
            idempotency_key=payload.idempotency_key,
            context=payload.context,
            callback_url=payload.callback_url
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if getattr(execution, "_is_new", True):
        try:
            arq_redis = await get_arq_redis()
            await arq_redis.enqueue_job("run_sequence_task", execution.id, _job_id=execution.id)
            logger.info(f"Enqueued named sequence task {execution.id} ({sequence_name_or_id}) into ARQ")
        except Exception as e:
            logger.error(f"Failed to enqueue task {execution.id} to ARQ: {e}")

    return execution

@router.post("/chain/trigger", response_model=SequenceExecutionResponseSchema)
async def trigger_chain_adhoc(
    payload: SequenceTriggerSchema, 
    db: Session = Depends(get_db)
):
    """
    Ad-hoc trigger endpoint allowing raw dynamic sequence payloads (backward compatible).
    """
    try:
        execution = SequenceManager.create_execution(
            db=db,
            sequence=payload.sequence,
            inputs=payload.inputs,
            mappings=payload.mappings,
            success_conditions=payload.success_conditions,
            idempotency_key=payload.idempotency_key,
            conditions=payload.conditions,
            context=payload.context,
            callback_url=payload.callback_url
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if getattr(execution, "_is_new", True):
        try:
            arq_redis = await get_arq_redis()
            await arq_redis.enqueue_job("run_sequence_task", execution.id, _job_id=execution.id)
            logger.info(f"Enqueued ad-hoc sequence task {execution.id} into ARQ")
        except Exception as e:
            logger.error(f"Failed to enqueue task {execution.id} to ARQ: {e}")

    return execution

@router.get("/chain/status/{execution_id}", response_model=SequenceExecutionResponseSchema)
async def get_chain_status(execution_id: str, db: Session = Depends(get_db)):
    """
    Retrieve the status, step execution traces, inputs, and outputs of a sequence run.
    """
    execution = db.query(SequenceExecution).filter(SequenceExecution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail=f"Sequence execution '{execution_id}' not found.")
    return execution

@router.post("/chain/cancel/{execution_id}")
async def cancel_chain(
    execution_id: str, 
    db: Session = Depends(get_db)
):
    """
    Cancel an active execution. Aborts the ARQ job and triggers Saga rollback.
    """
    execution = db.query(SequenceExecution).filter(SequenceExecution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail=f"Sequence execution '{execution_id}' not found.")
    
    if execution.status not in ["PENDING", "RUNNING"]:
        raise HTTPException(status_code=400, detail=f"Cannot cancel execution in status '{execution.status}'.")

    execution.status = "FAILED"
    execution.error_message = "Cancelled by user"
    execution.steps_data = [s for s in execution.steps_data if s["status"] != "PENDING"]
    db.commit()

    completed_steps = []
    for step in execution.steps_data:
        if step["status"] == "COMPLETED":
            completed_steps.append((step["service_name"], step["input_payload"], step["output_response"]))

    try:
        arq_redis = await get_arq_redis()
        job = Job(execution_id, arq_redis)
        await job.abort()
        
        if completed_steps:
            await arq_redis.enqueue_job("rollback_sequence_task", execution.id, completed_steps)
            
        return {"detail": "Cancellation command issued and ARQ job aborted."}
    except Exception as e:
        logger.warning(f"Could not signal ARQ abort for job {execution_id}: {e}")
        return {"detail": "Cancellation recorded in database.", "warning": str(e)}

@router.post("/chain/retry/{execution_id}", response_model=SequenceExecutionResponseSchema)
async def retry_chain(
    execution_id: str,
    payload: SequenceRetrySchema,
    db: Session = Depends(get_db)
):
    """
    Retry a failed or partially successful orchestration sequence.
    Strategies:
      - 'restart': Clear steps data and run again from scratch.
      - 'resume': Preserve completed steps and continue running from the first failed step.
    """
    execution = db.query(SequenceExecution).filter(SequenceExecution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail=f"Sequence execution '{execution_id}' not found.")
    
    if execution.status not in ["FAILED", "PARTIAL_SUCCESS"]:
        raise HTTPException(status_code=400, detail=f"Only failed or partially successful executions can be retried. Current status is '{execution.status}'.")

    if payload.strategy == "restart":
        execution.status = "PENDING"
        execution.error_message = None
        execution.current_step = 0
        execution.steps_data = []
        db.commit()
    elif payload.strategy == "resume":
        execution.status = "PENDING"
        execution.error_message = None
        
        current_steps = list(execution.steps_data)
        has_failed = False
        first_failed_idx = 0
        for idx, step in enumerate(current_steps):
            if step["status"] in ["FAILED", "RUNNING"]:
                step["status"] = "PENDING"
                step["error_message"] = None
                step["started_at"] = None
                step["finished_at"] = None
                step["duration_ms"] = 0
                step["retry_count"] = 0
                if not has_failed:
                    first_failed_idx = idx
                    has_failed = True
        
        execution.steps_data = current_steps
        execution.current_step = first_failed_idx
        db.commit()
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported retry strategy '{payload.strategy}'. Use 'restart' or 'resume'.")

    try:
        arq_redis = await get_arq_redis()
        import uuid
        retry_job_id = f"{execution.id}-retry-{uuid.uuid4().hex[:6]}"
        await arq_redis.enqueue_job("run_sequence_task", execution.id, _job_id=retry_job_id)
        logger.info(f"Enqueued retry task {execution.id} into ARQ as {retry_job_id}")
    except Exception as e:
        logger.error(f"Failed to enqueue retry task {execution.id} to ARQ: {e}")

    return execution
