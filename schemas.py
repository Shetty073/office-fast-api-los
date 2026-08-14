from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union
from datetime import datetime

class MappingSchema(BaseModel):
    from_service: str = Field(..., description="Name of the source service")
    from_field: str = Field(..., description="Dot-notated path of the output field to copy")
    to_service: str = Field(..., description="Name of the target service")
    to_field: str = Field(..., description="Dot-notated path of the input field to populate")
    transform: Optional[str] = Field(None, description="Optional transformation type (e.g. to_int, to_str, upper, lower)")

class SequenceTriggerSchema(BaseModel):
    sequence: List[Union[str, List[str]]] = Field(..., description="Ordered list of service names to run. Nested lists run in parallel.")
    inputs: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict, 
        description="Initial payload mapping for services (service_name -> payload dict)"
    )
    mappings: List[MappingSchema] = Field(
        default_factory=list,
        description="Data mapping definitions between services in the sequence"
    )
    success_conditions: Optional[Dict[str, Dict[str, Any]]] = Field(
        default=None,
        description="Optional success condition overrides for services (service_name -> conditions dict)"
    )
    idempotency_key: Optional[str] = Field(
        default=None,
        description="Unique key to prevent duplicate runs of the same orchestration."
    )
    conditions: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional execution conditions (service_name -> python boolean expression string)"
    )
    context: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Optional global shared context dictionary."
    )
    callback_url: Optional[str] = Field(
        default=None,
        description="Optional callback URL for webhook updates."
    )

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
    sequence: List[Union[str, List[str]]]
    inputs: Dict[str, Dict[str, Any]]
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
