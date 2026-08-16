from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union
from datetime import datetime

class MappingSchema(BaseModel):
    from_service: str = Field(..., description="Name of the source service (e.g. 'trigger_payload', 'context', or 'todo_service')")
    from_field: str = Field(..., description="Dot-notated path of the output field to copy")
    to_service: str = Field(..., description="Name of the target service")
    to_field: str = Field(..., description="Dot-notated path of the input field to populate")
    transform: Optional[str] = Field(None, description="Optional transformation type (e.g. to_int, to_str, upper, lower)")

# Schema to register / create a sequence recipe in DB
class SequenceDefinitionCreateSchema(BaseModel):
    name: str = Field(..., description="Unique alphanumeric identifier for the sequence (e.g. 'user_onboarding')")
    description: Optional[str] = Field(None, description="Human readable description of the workflow")
    sequence: List[Union[str, List[str]]] = Field(..., description="Ordered list of service names. Sub-lists execute concurrently in parallel.")
    default_inputs: Optional[Dict[str, Dict[str, Any]]] = Field(default_factory=dict, description="Default static inputs per service")
    mappings: List[MappingSchema] = Field(default_factory=list, description="Parameter mappings from trigger payload / prior steps to downstream steps")
    success_conditions: Optional[Dict[str, Dict[str, Any]]] = Field(default=None, description="Custom success rules per service")
    conditions: Optional[Dict[str, str]] = Field(default=None, description="Execution boolean condition expressions per service")

class SequenceDefinitionResponseSchema(SequenceDefinitionCreateSchema):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Schema for triggering a registered sequence by name
class TriggerSequencePayloadSchema(BaseModel):
    payload: Dict[str, Any] = Field(default_factory=dict, description="Initial parameters passed to the sequence (accessible as 'trigger_payload')")
    inputs_override: Optional[Dict[str, Dict[str, Any]]] = Field(default_factory=dict, description="Optional override for static service inputs")
    idempotency_key: Optional[str] = Field(default=None, description="Unique key to prevent duplicate runs")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Optional initial shared context dictionary")
    callback_url: Optional[str] = Field(default=None, description="Optional callback URL for webhook notification")

# Raw Ad-hoc Trigger Schema (backward compatible)
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
    steps_data: List[StepExecutionSchema]
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class SequenceRetrySchema(BaseModel):
    strategy: str = Field(..., description="Retry strategy: 'restart' or 'resume'")
