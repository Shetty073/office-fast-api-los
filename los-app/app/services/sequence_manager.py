import uuid
from typing import List, Dict, Any, Optional, Union
from sqlalchemy.orm import Session
from app.models.sequence_definition import SequenceDefinition
from app.models.sequence_execution import SequenceExecution
from app.services.registry import ServiceRegistry
from app.core.utils import get_by_path, set_by_path

class SequenceManager:
    """
    Manages sequence definitions and execution lifecycle records in the database.
    """
    @staticmethod
    def create_definition(
        db: Session,
        name: str,
        sequence: List[Union[str, List[str]]],
        description: Optional[str] = None,
        default_inputs: Optional[Dict[str, Dict[str, Any]]] = None,
        mappings: Optional[List[Any]] = None,
        success_conditions: Optional[Dict[str, Dict[str, Any]]] = None,
        conditions: Optional[Dict[str, str]] = None
    ) -> SequenceDefinition:
        for item in sequence:
            if isinstance(item, list):
                for s in item:
                    if s not in ServiceRegistry.list_services():
                        raise KeyError(f"Service '{s}' is not registered.")
            else:
                if item not in ServiceRegistry.list_services():
                    raise KeyError(f"Service '{item}' is not registered.")

        serialized_mappings = []
        for m in (mappings or []):
            if hasattr(m, "model_dump"):
                serialized_mappings.append(m.model_dump())
            elif isinstance(m, dict):
                serialized_mappings.append(m)
            else:
                serialized_mappings.append(dict(m))

        existing = db.query(SequenceDefinition).filter(SequenceDefinition.name == name).first()
        if existing:
            existing.sequence = sequence
            existing.description = description
            existing.default_inputs = default_inputs or {}
            existing.mappings = serialized_mappings
            existing.success_conditions = success_conditions
            existing.conditions = conditions
            db.commit()
            db.refresh(existing)
            return existing

        seq_def = SequenceDefinition(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            sequence=sequence,
            default_inputs=default_inputs or {},
            mappings=serialized_mappings,
            success_conditions=success_conditions,
            conditions=conditions
        )
        db.add(seq_def)
        db.commit()
        db.refresh(seq_def)
        return seq_def

    @staticmethod
    def trigger_by_definition(
        db: Session,
        sequence_name_or_id: str,
        trigger_payload: Optional[Dict[str, Any]] = None,
        inputs_override: Optional[Dict[str, Dict[str, Any]]] = None,
        idempotency_key: Optional[str] = None,
        previous_task_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        callback_url: Optional[str] = None
    ) -> SequenceExecution:
        # 1. If previous_task_id is provided, resume from the point of failure
        if previous_task_id:
            prev_exec = db.query(SequenceExecution).filter(
                (SequenceExecution.id == previous_task_id)
            ).first()
            if not prev_exec:
                raise KeyError(f"Previous task ID '{previous_task_id}' not found.")
            
            if prev_exec.status not in ["FAILED", "PARTIAL_SUCCESS"]:
                raise ValueError(f"Cannot resume task '{previous_task_id}' with status '{prev_exec.status}'. Only failed tasks can be resumed.")

            prev_exec.status = "PENDING"
            prev_exec.error_message = None
            
            current_steps = list(prev_exec.steps_data or [])
            has_failed = False
            first_failed_idx = 0
            for idx, step in enumerate(current_steps):
                if step.get("status") in ["FAILED", "RUNNING"]:
                    step["status"] = "PENDING"
                    step["error_message"] = None
                    step["started_at"] = None
                    step["finished_at"] = None
                    step["duration_ms"] = 0
                    step["retry_count"] = 0
                    if not has_failed:
                        first_failed_idx = idx
                        has_failed = True
            
            prev_exec.steps_data = current_steps
            prev_exec.current_step = first_failed_idx
            db.commit()
            db.refresh(prev_exec)
            prev_exec._is_new = True
            return prev_exec

        # 2. Check Idempotency Key
        if idempotency_key:
            existing = db.query(SequenceExecution).filter(
                SequenceExecution.idempotency_key == idempotency_key
            ).first()
            if existing:
                existing._is_new = False
                return existing

        seq_def = db.query(SequenceDefinition).filter(
            (SequenceDefinition.name == sequence_name_or_id) | (SequenceDefinition.id == sequence_name_or_id)
        ).first()

        if not seq_def:
            raise KeyError(f"Sequence definition '{sequence_name_or_id}' not found.")

        combined_inputs = dict(seq_def.default_inputs or {})
        if inputs_override:
            for s_name, s_payload in inputs_override.items():
                if s_name not in combined_inputs:
                    combined_inputs[s_name] = {}
                combined_inputs[s_name].update(s_payload)

        trigger_data = trigger_payload or {}
        for m in seq_def.mappings:
            if m.get("from_service") == "trigger_payload":
                from_field = m.get("from_field")
                to_service = m.get("to_service")
                to_field = m.get("to_field")
                val = get_by_path(trigger_data, from_field)
                if val is not None:
                    transform = m.get("transform")
                    if transform == "to_int":
                        try:
                            val = int(val)
                        except (ValueError, TypeError):
                            pass
                    elif transform == "to_str":
                        val = str(val)
                    elif transform == "upper" and isinstance(val, str):
                        val = val.upper()
                    elif transform == "lower" and isinstance(val, str):
                        val = val.lower()
                    
                    if to_service not in combined_inputs:
                        combined_inputs[to_service] = {}
                    set_by_path(combined_inputs[to_service], to_field, val)

        execution = SequenceExecution(
            id=str(uuid.uuid4()),
            sequence_name=seq_def.name,
            sequence=seq_def.sequence,
            inputs=combined_inputs,
            trigger_payload=trigger_data,
            mappings=seq_def.mappings,
            success_conditions=seq_def.success_conditions,
            idempotency_key=idempotency_key,
            conditions=seq_def.conditions,
            context=context or {},
            callback_url=callback_url,
            status="PENDING",
            current_step=0,
            steps_data=[]
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)
        execution._is_new = True
        return execution

    @staticmethod
    def create_execution(
        db: Session, 
        sequence: List[Union[str, List[str]]], 
        inputs: Dict[str, Any], 
        mappings: List[Any],
        success_conditions: Optional[Dict[str, Dict[str, Any]]] = None,
        idempotency_key: Optional[str] = None,
        conditions: Optional[Dict[str, str]] = None,
        context: Optional[Dict[str, Any]] = None,
        callback_url: Optional[str] = None
    ) -> SequenceExecution:
        if idempotency_key:
            existing = db.query(SequenceExecution).filter(
                SequenceExecution.idempotency_key == idempotency_key
            ).first()
            if existing:
                existing._is_new = False
                return existing

        for item in sequence:
            if isinstance(item, list):
                for name in item:
                    if name not in ServiceRegistry.list_services():
                        raise KeyError(f"Service '{name}' is not registered.")
            else:
                if item not in ServiceRegistry.list_services():
                    raise KeyError(f"Service '{item}' is not registered.")

        serialized_mappings = []
        for m in mappings:
            if hasattr(m, "model_dump"):
                serialized_mappings.append(m.model_dump())
            elif isinstance(m, dict):
                serialized_mappings.append(m)
            else:
                serialized_mappings.append(dict(m))

        execution = SequenceExecution(
            id=str(uuid.uuid4()),
            sequence=sequence,
            inputs=inputs,
            mappings=serialized_mappings,
            success_conditions=success_conditions,
            idempotency_key=idempotency_key,
            conditions=conditions,
            context=context or {},
            callback_url=callback_url,
            status="PENDING",
            current_step=0,
            steps_data=[]
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)
        execution._is_new = True
        return execution
