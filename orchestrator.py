import uuid
import time
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from models import SequenceExecution
from services.registry import ServiceRegistry
from utils import get_by_path, set_by_path

logger = logging.getLogger(__name__)

class Orchestrator:
    @staticmethod
    def create_execution(
        db: Session, 
        sequence: List[str], 
        inputs: Dict[str, Any], 
        mappings: List[Any],
        success_conditions: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> SequenceExecution:
        """
        Validate services exist, initialize the sequence execution model and save to the DB.
        """
        # Ensure all services exist
        for name in sequence:
            try:
                ServiceRegistry.get(name)
            except KeyError:
                raise KeyError(f"Service '{name}' is not registered and cannot be sequenced.")

        # Serialize mappings to dicts
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
            status="PENDING",
            current_step=0,
            steps_data=[]
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)
        return execution

    @classmethod
    async def run_sequence(cls, execution_id: str, get_db_session):
        """
        Runs the sequence of service calls asynchronously in a background worker task context.
        Provides support for inputs mapping, retries, step latency logging, and partial success states.
        """
        db_gen = get_db_session()
        db = next(db_gen)
        try:
            execution = db.query(SequenceExecution).filter(SequenceExecution.id == execution_id).first()
            if not execution:
                logger.error(f"Execution {execution_id} not found.")
                return

            execution.status = "RUNNING"
            db.commit()

            responses: Dict[str, Dict[str, Any]] = {}
            steps_data = []
            has_partial_failure = False

            for idx, service_name in enumerate(execution.sequence):
                execution.current_step = idx + 1
                db.commit()

                service = ServiceRegistry.get(service_name)

                step_info = {
                    "service_name": service_name,
                    "status": "RUNNING",
                    "input_payload": {},
                    "output_response": None,
                    "error_message": None,
                    "started_at": datetime.utcnow().isoformat(),
                    "finished_at": None,
                    "duration_ms": 0,
                    "retry_count": 0
                }
                steps_data.append(step_info)
                execution.steps_data = steps_data
                db.commit()

                # Copy service static inputs
                payload = execution.inputs.get(service_name, {}).copy()

                # Extract optional runtime mock override from input parameters
                mock_override = payload.pop("_mock", None)

                # Resolve incoming mappings from previous service output fields
                for mapping in execution.mappings:
                    if mapping.get("to_service") == service_name:
                        from_service = mapping.get("from_service")
                        if from_service in responses:
                            prev_response = responses[from_service]
                            # Only map if previous service was successful and has data block
                            if prev_response.get("success") and prev_response.get("data") is not None:
                                source_data = prev_response["data"]
                                from_field = mapping.get("from_field")
                                to_field = mapping.get("to_field")
                                
                                val = get_by_path(source_data, from_field)
                                if val is not None:
                                    set_by_path(payload, to_field, val)

                step_info["input_payload"] = payload
                execution.steps_data = steps_data
                db.commit()

                # Executing retry loop
                retries = 0
                max_retries = service.max_retries
                step_success = False
                service_response = None
                step_error = None
                start_step_time = time.time()

                while retries <= max_retries:
                    step_info["retry_count"] = retries
                    execution.steps_data = steps_data
                    db.commit()

                    try:
                        conditions = None
                        if execution.success_conditions and isinstance(execution.success_conditions, dict):
                            conditions = execution.success_conditions.get(service_name)

                        service_response = await service.execute(
                            payload=payload, 
                            execution_id=execution_id, 
                            mock_override=mock_override,
                            success_conditions=conditions
                        )
                        if service_response.get("success"):
                            step_success = True
                            break
                        else:
                            step_error = service_response.get("error", "Service execution succeeded but returned success=False")
                    except Exception as e:
                        step_error = str(e)

                    retries += 1
                    if retries <= max_retries:
                        await asyncio.sleep(1)  # simple delay between retries

                step_info["finished_at"] = datetime.utcnow().isoformat()
                step_info["duration_ms"] = int((time.time() - start_step_time) * 1000)

                if step_success:
                    step_info["status"] = "COMPLETED"
                    step_info["output_response"] = service_response
                    responses[service_name] = service_response
                else:
                    step_info["status"] = "FAILED"
                    step_info["error_message"] = step_error
                    if service_response:
                        step_info["output_response"] = service_response
                        responses[service_name] = service_response

                    if service.is_critical:
                        execution.status = "FAILED"
                        execution.error_message = f"Failed at critical step {idx+1} ({service_name}): {step_error}"
                        execution.steps_data = steps_data
                        db.commit()
                        return
                    else:
                        has_partial_failure = True
                        responses[service_name] = service_response or {
                            "success": False, 
                            "data": None, 
                            "error": step_error,
                            "status_code": 500
                        }

                execution.steps_data = steps_data
                db.commit()

            # Finalize overall execution status
            execution.status = "PARTIAL_SUCCESS" if has_partial_failure else "COMPLETED"
            db.commit()

        except Exception as e:
            logger.exception(f"Internal Orchestrator failure: {e}")
            try:
                execution = db.query(SequenceExecution).filter(SequenceExecution.id == execution_id).first()
                if execution:
                    execution.status = "FAILED"
                    execution.error_message = f"Orchestrator error: {str(e)}"
                    db.commit()
            except Exception:
                pass
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass
