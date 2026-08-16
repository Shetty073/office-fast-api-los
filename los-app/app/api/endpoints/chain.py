from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from arq.jobs import Job
from app.db.session import get_db
from app.models.sequence_execution import SequenceExecution
from app.services.sequence_manager import SequenceManager
from app.schemas.sequence_execution import (
    TriggerSequencePayloadSchema,
    TriggerResponseSchema,
    SequenceTriggerSchema,
    SequenceExecutionResponseSchema,
    SequenceRetrySchema
)
from app.core.redis_pool import get_arq_redis
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/trigger/{sequence_name_or_id}", response_model=TriggerResponseSchema)
async def trigger_by_sequence_name(
    sequence_name_or_id: str,
    payload: TriggerSequencePayloadSchema,
    db: Session = Depends(get_db)
):
    """
    Trigger a named sequence recipe.
    Returns only task_id and task_name.
    If 'previous_task_id' is provided, resumes from the point of failure.
    """
    try:
        execution = SequenceManager.trigger_by_definition(
            db=db,
            sequence_name_or_id=sequence_name_or_id,
            trigger_payload=payload.payload,
            inputs_override=payload.inputs_override,
            idempotency_key=payload.idempotency_key,
            previous_task_id=payload.previous_task_id,
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
            job_id = f"{execution.id}-run"
            await arq_redis.enqueue_job("run_sequence_task", execution.id, _job_id=job_id)
            logger.info(f"Enqueued sequence task {execution.id} ({sequence_name_or_id}) into ARQ")
        except Exception as e:
            logger.error(f"Failed to enqueue task {execution.id} to ARQ: {e}")

    return {
        "task_id": execution.id,
        "task_name": execution.sequence_name or sequence_name_or_id
    }

@router.post("/trigger", response_model=SequenceExecutionResponseSchema)
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

@router.get("/status/{execution_id}", response_model=SequenceExecutionResponseSchema)
async def get_chain_status(execution_id: str, db: Session = Depends(get_db)):
    """
    Retrieve the status, step execution traces, inputs, outputs, and task counts of a sequence run.
    """
    execution = db.query(SequenceExecution).filter(SequenceExecution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail=f"Sequence execution '{execution_id}' not found.")
    return execution

@router.post("/cancel/{execution_id}")
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

@router.post("/retry/{execution_id}", response_model=SequenceExecutionResponseSchema)
async def retry_chain(
    execution_id: str,
    payload: SequenceRetrySchema,
    db: Session = Depends(get_db)
):
    """
    Retry a failed or partially successful orchestration sequence.
    Strategies: 'restart' or 'resume'.
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
        
        current_steps = [dict(s) for s in execution.steps_data]
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
        db.refresh(execution)
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
