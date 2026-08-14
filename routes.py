from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
from database import get_db
from models import SequenceExecution
from services.registry import ServiceRegistry
from orchestrator import Orchestrator
from schemas import SequenceTriggerSchema, SequenceExecutionResponseSchema

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
            mappings=payload.mappings
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Hand off execution to background task worker
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
