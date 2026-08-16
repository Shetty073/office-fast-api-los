from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from app.schemas.mapping import MappingSchema

class TriggerSequencePayloadSchema(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict, description="Dynamic input parameters to trigger the sequence with")
    idempotency_key: Optional[str] = Field(None, description="Client-provided idempotency key (100 char max)")
    callback_url: Optional[str] = Field(None, description="Optional webhook URL to receive progress / completion events")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Initial global context dictionary")
    previous_task_id: Optional[str] = Field(None, description="Optional previous task_id to resume from point of failure")

class TriggerResponseSchema(BaseModel):
    task_id: str = Field(..., description="Unique UUID identifier of the triggered sequence execution")
    task_name: str = Field(..., description="Name of the triggered sequence recipe")

class SequenceExecutionCreateSchema(BaseModel):
    sequence: List[Union[str, List[str]]] = Field(..., description="Ordered list of services to execute. Sub-lists execute in parallel.")
    inputs: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="Static base inputs mapped to each service name")
    mappings: List[MappingSchema] = Field(default_factory=list, description="Cross-service payload transformation rules")
    success_conditions: Optional[Dict[str, Dict[str, Any]]] = Field(default=None, description="Custom success rules per service")
    idempotency_key: Optional[str] = Field(None, description="Client-provided idempotency key (100 char max)")
    conditions: Optional[Dict[str, str]] = Field(default=None, description="Execution boolean condition expressions per service")
    skip_conditions: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]] = Field(default=None, description="Skip condition rules")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Initial execution state context")
    callback_url: Optional[str] = Field(None, description="Optional webhook URL for status callbacks")

class StepExecutionSchema(BaseModel):
    service_name: str
    status: str
    input_payload: Dict[str, Any]
    output_response: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    retry_count: Optional[int] = None

class TaskCountSchema(BaseModel):
    total: int
    completed: int
    failed: int = 0
    pending: int

class SequenceStatusResponseSchema(BaseModel):
    task_id: str
    status: str
    count: TaskCountSchema
    data: Dict[str, Any] = Field(default_factory=dict, description="Consolidated dictionary of response of each task")

    class Config:
        from_attributes = True

class SequenceExecutionResponseSchema(BaseModel):
    id: str
    sequence_name: Optional[str] = None
    sequence: List[Union[str, List[str]]]
    inputs: Dict[str, Dict[str, Any]]
    trigger_payload: Optional[Dict[str, Any]] = None
    mappings: List[MappingSchema]
    success_conditions: Optional[Dict[str, Dict[str, Any]]] = None
    idempotency_key: Optional[str] = None
    conditions: Optional[Dict[str, str]] = None
    skip_conditions: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]] = None
    context: Optional[Dict[str, Any]] = None
    callback_url: Optional[str] = None
    status: str
    current_step: int
    total_tasks: int = 0
    completed_tasks: int = 0
    pending_tasks: int = 0
    responses: Dict[str, Any] = Field(default_factory=dict, description="Consolidated dictionary of all executed API responses")
    steps_data: List[StepExecutionSchema]
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class SequenceRetrySchema(BaseModel):
    strategy: str = Field(..., description="Retry strategy: 'restart' or 'resume'")
