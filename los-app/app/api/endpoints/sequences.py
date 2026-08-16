from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.db.session import get_db
from app.models.sequence_definition import SequenceDefinition
from app.models.user import User
from app.api.deps import get_current_admin_user
from app.services.sequence_manager import SequenceManager
from app.schemas.sequence_definition import SequenceDefinitionCreateSchema, SequenceDefinitionResponseSchema

router = APIRouter()

@router.post("", response_model=SequenceDefinitionResponseSchema)
def create_or_update_sequence_definition(
    payload: SequenceDefinitionCreateSchema,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    Register or update a sequence definition recipe in the database. (Admin only)
    Allows authorized administrators to configure new sequences without touching orchestrator code.
    """
    try:
        seq_def = SequenceManager.create_definition(
            db=db,
            name=payload.name,
            sequence=payload.sequence,
            description=payload.description,
            default_inputs=payload.default_inputs,
            mappings=payload.mappings,
            success_conditions=payload.success_conditions,
            conditions=payload.conditions
        )
        return seq_def
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("", response_model=List[SequenceDefinitionResponseSchema])
def list_sequence_definitions(
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """List all registered sequence recipes stored in the database. (Admin only)"""
    return db.query(SequenceDefinition).all()

@router.get("/{name_or_id}", response_model=SequenceDefinitionResponseSchema)
def get_sequence_definition(
    name_or_id: str, 
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """Retrieve a specific sequence recipe by its name or ID. (Admin only)"""
    seq_def = db.query(SequenceDefinition).filter(
        (SequenceDefinition.name == name_or_id) | (SequenceDefinition.id == name_or_id)
    ).first()
    if not seq_def:
        raise HTTPException(status_code=404, detail=f"Sequence definition '{name_or_id}' not found.")
    return seq_def
