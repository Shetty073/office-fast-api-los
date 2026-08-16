from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from app.schemas.mapping import MappingSchema

class TriggerSequencePayloadSchema(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict, description="Initial parameters passed to the sequence (accessible as 'trigger_payload')")
    inputs_override: Optional[Dict[str, Dict[str, Any]]] = Field(default_factory=dict, description="Optional override for static service inputs")
    idempotency_key: Optional[str] = Field(default=None, description="Unique key to prevent duplicate runs")
    previous_task_id: Optional[str] = Field(default=None, description="Pass previous failed task ID to resume from point of failure")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Optional initial shared context dictionary")
    callback_url: Optional[str] = Field(default=None, description="Optional callback URL for webhook notification")

class TriggerResponseSchema(BaseModel):
    task_id: str = Field(..., description="Unique execution ID of the triggered task sequence")
    task_name: str = Field(..., description="Name of the sequence recipe or dynamic task")

class SequenceTriggerSchema(BaseModel):
    sequence: List[Union[str, List[str]]] = Field(..., description="Ordered list of service names to run. Nested lists run in parallel.")
    inputs: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="Initial payload mapping for services")
    mappings: List[MappingSchema] = Field(default_factory=list, description="Data mapping definitions")
    success_conditions: Optional[Dict[str, Dict[str, Any]]] = Field(default=None)
    idempotency_key: Optional[str] = Field(default=None)
    conditions: Optional[Dict[str, str]] = Field(default=None)
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)
    callback_url: Optional[str] = Field(default=None)

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
