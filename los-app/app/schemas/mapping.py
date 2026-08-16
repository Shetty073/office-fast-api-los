from pydantic import BaseModel, Field
from typing import Optional

class MappingSchema(BaseModel):
    from_service: str = Field(..., description="Name of the source service (e.g. 'trigger_payload', 'context', or 'todo_service')")
    from_field: str = Field(..., description="Dot-notated path of the output field to copy")
    to_service: str = Field(..., description="Name of the target service")
    to_field: str = Field(..., description="Dot-notated path of the input field to populate")
    transform: Optional[str] = Field(None, description="Optional transformation type (e.g. to_int, to_str, upper, lower)")
