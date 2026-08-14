from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from database import get_db
from models import SequenceExecution
from services.registry import ServiceRegistry
from orchestrator import Orchestrator
from schemas import SequenceTriggerSchema, SequenceExecutionResponseSchema, SequenceRetrySchema

router = APIRouter(prefix="/api")

@router.post("/standalone/{service_name}")
async def call_standalone(
    service_name: str, 
    payload: Dict[str, Any], 
    mock: Optional[bool] = Query(None, description="Force enable/disable mock for this execution")
):
    """
    1st Endpoint: Standalone dynamic API call.
    Finds the service from the registry by its name, executes it, and returns the standard response.
    """
    try:
        service = ServiceRegistry.get(service_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Service '{service_name}' not found.")

    result = await service.execute(payload, mock_override=mock)
    
    if not result.get("success"):
        raise HTTPException(
            status_code=result.get("status_code", 400), 
            detail=result.get("error", "Service failed during execution.")
        )
        
    return result

@router.post("/chain/trigger", response_model=SequenceExecutionResponseSchema)
async def trigger_chain(
    payload: SequenceTriggerSchema, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db)
):
    """
    2nd Endpoint: Trigger a sequence of service executions.
    Saves the execution plan in the database and launches execution in a FastAPI BackgroundTask.
    """
    try:
        execution = Orchestrator.create_execution(
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

    # Hand off execution to background task worker if the execution is brand new
    if getattr(execution, "_is_new", True):
        background_tasks.add_task(Orchestrator.run_sequence, execution.id, get_db)
    return execution

@router.get("/chain/status/{execution_id}", response_model=SequenceExecutionResponseSchema)
async def get_chain_status(execution_id: str, db: Session = Depends(get_db)):
    """
    3rd Endpoint: Retrieve the status, logs, steps, and responses of a sequence execution.
    """
    execution = db.query(SequenceExecution).filter(SequenceExecution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail=f"Sequence execution '{execution_id}' not found.")
    return execution

@router.post("/chain/cancel/{execution_id}")
async def cancel_chain(
    execution_id: str, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db)
):
    """
    Cancel an active execution. Triggers Saga rollback compensating transactions on completed steps.
    """
    execution = db.query(SequenceExecution).filter(SequenceExecution.id == execution_id).first()
    if not execution:
        raise HTTPException(status_code=404, detail=f"Sequence execution '{execution_id}' not found.")
    
    if execution.status not in ["PENDING", "RUNNING"]:
        raise HTTPException(status_code=400, detail=f"Cannot cancel execution in status '{execution.status}'.")

    # Change status to FAILED in DB first (so it doesn't try to continue)
    execution.status = "FAILED"
    execution.error_message = "Cancelled by user"
    # Remove PENDING placeholders
    execution.steps_data = [s for s in execution.steps_data if s["status"] != "PENDING"]
    db.commit()

    # Look up in active_tasks map and cancel
    task = Orchestrator.active_tasks.get(execution_id)
    if task:
        task.cancel()
        return {"detail": "Cancellation command issued and background task interrupted."}
    else:
        # If not active in background memory map, trigger SAGA rollback manually here
        # (This is a safety fallback for pending/orphaned tasks)
        from orchestrator import ServiceRegistry, APIClient
        completed_steps = []
        for step in execution.steps_data:
            if step["status"] == "COMPLETED":
                completed_steps.append((step["service_name"], step["input_payload"], step["output_response"]))
        
        async def rollback():
            for name, payload, response in reversed(completed_steps):
                service = ServiceRegistry.get(name)
                client = APIClient(service_name=service.name, execution_id=execution_id, timeout=service.timeout)
                try:
                    await service.compensate(payload=payload, response=response, client=client)
                except Exception:
                    pass
        background_tasks.add_task(rollback)
        return {"detail": "Cancellation issued: Task was not active in worker map. Executed compensating transactions manually.", "manual_rollback_triggered": True}

@router.post("/chain/retry/{execution_id}", response_model=SequenceExecutionResponseSchema)
async def retry_chain(
    execution_id: str,
    payload: SequenceRetrySchema,
    background_tasks: BackgroundTasks,
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
        # Reset everything to fresh state
        execution.status = "PENDING"
        execution.error_message = None
        execution.current_step = 0
        execution.steps_data = []  # Clear steps data so it gets re-initialized fresh
        db.commit()
    elif payload.strategy == "resume":
        # Reset failed steps to pending so they run again. Keep completed steps intact.
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

    # Launch background task
    background_tasks.add_task(Orchestrator.run_sequence, execution.id, get_db)
    return execution
