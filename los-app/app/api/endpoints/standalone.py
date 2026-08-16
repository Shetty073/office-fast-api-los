from fastapi import APIRouter, HTTPException, Query, Header
from typing import Dict, Any, Optional
from app.services.registry import ServiceRegistry
from app.core.utils import APIClient

router = APIRouter()

@router.post("/{service_name}")
async def call_standalone(
    service_name: str, 
    payload: Dict[str, Any], 
    mock: Optional[bool] = Query(None, description="Force enable/disable mock for this execution"),
    x_execution_source: Optional[str] = Header(default="standalone", alias="X-Execution-Source"),
    x_execution_id: Optional[str] = Header(default=None, alias="X-Execution-Id")
):
    """
    Standalone dynamic API call.
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

@router.post("/{service_name}/compensate")
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
