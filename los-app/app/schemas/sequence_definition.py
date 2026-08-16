from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
from app.schemas.mapping import MappingSchema

class SequenceDefinitionCreateSchema(BaseModel):
    name: str = Field(..., description="Unique alphanumeric identifier for the sequence (e.g. 'user_onboarding')")
    description: Optional[str] = Field(None, description="Human readable description of the workflow")
    sequence: List[Union[str, List[str]]] = Field(..., description="Ordered list of service names. Sub-lists execute concurrently in parallel.")
    default_inputs: Optional[Dict[str, Dict[str, Any]]] = Field(default_factory=dict, description="Default static inputs per service")
    mappings: List[MappingSchema] = Field(default_factory=list, description="Parameter mappings from trigger payload / prior steps to downstream steps")
    success_conditions: Optional[Dict[str, Dict[str, Any]]] = Field(default=None, description="Custom success rules per service")
    conditions: Optional[Dict[str, str]] = Field(default=None, description="Execution boolean condition expressions per service")
    skip_conditions: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]] = Field(default=None, description="List of rules to skip a step based on condition evaluations")

class SequenceDefinitionResponseSchema(SequenceDefinitionCreateSchema):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
