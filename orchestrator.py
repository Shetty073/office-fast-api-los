import uuid
import time
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Union
from sqlalchemy.orm import Session
from models import SequenceExecution
from services.registry import ServiceRegistry
from utils import get_by_path, set_by_path, APIClient

logger = logging.getLogger(__name__)

def evaluate_condition(expression: str, responses: Dict[str, Any], context: Dict[str, Any]) -> bool:
    """
    Safely evaluate a simple boolean expression string.
    Exposes 'responses' and 'context' to the expression namespace.
    """
    if not expression:
        return True
    try:
        class DotDict:
            def __init__(self, d):
                for k, v in d.items():
                    if isinstance(v, dict):
                        setattr(self, k, DotDict(v))
                    elif isinstance(v, list):
                        setattr(self, k, [DotDict(item) if isinstance(item, dict) else item for item in v])
                    else:
                        setattr(self, k, v)
            def __getattr__(self, name):
                return None
        
        wrapped_responses = DotDict(responses)
        wrapped_context = DotDict(context)
        
        allowed_globals = {
            "responses": wrapped_responses,
            "context": wrapped_context,
            "True": True,
            "False": False,
            "None": None
        }
        return bool(eval(expression, allowed_globals, {}))
    except Exception as e:
        logger.error(f"Error evaluating condition '{expression}': {e}")
        return False

class Orchestrator:
    active_tasks: Dict[str, asyncio.Task] = {}

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
        """
        Validate services exist, initialize the sequence execution model and save to the DB.
        Checks idempotency key to prevent duplicate runs.
        """
        if idempotency_key:
            existing = db.query(SequenceExecution).filter(
                SequenceExecution.idempotency_key == idempotency_key
            ).first()
            if existing:
                existing._is_new = False
                return existing

        # Ensure all services exist
        for item in sequence:
            if isinstance(item, list):
                for name in item:
                    try:
                        ServiceRegistry.get(name)
                    except KeyError:
                        raise KeyError(f"Service '{name}' is not registered and cannot be sequenced.")
            else:
                try:
                    ServiceRegistry.get(item)
                except KeyError:
                    raise KeyError(f"Service '{item}' is not registered and cannot be sequenced.")

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

    @classmethod
    async def run_sequence(cls, execution_id: str, get_db_session):
        """
        Runs the sequence of service calls asynchronously in a background worker task context.
        Provides support for inputs mapping, retries, step latency logging, Saga rollbacks,
        parallel executions, and partial success states.
        """
        cls.active_tasks[execution_id] = asyncio.current_task()
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
            completed_steps = []  # List of tuples: (service_name, input_payload, output_response)
            has_partial_failure = False

            # Initialize steps_data structure for all steps upfront if not already populated
            if not execution.steps_data:
                steps_data = []
                flat_services = []
                for step_item in execution.sequence:
                    if isinstance(step_item, list):
                        flat_services.extend(step_item)
                    else:
                        flat_services.append(step_item)

                for name in flat_services:
                    steps_data.append({
                        "service_name": name,
                        "status": "PENDING",
                        "input_payload": {},
                        "output_response": None,
                        "error_message": None,
                        "started_at": None,
                        "finished_at": None,
                        "duration_ms": 0,
                        "retry_count": 0
                    })
                execution.steps_data = steps_data
                db.commit()

            # Helper for executing a single step logic
            async def run_single_step(service_name: str, step_idx: int):
                # Check if this step is already completed from a previous run (Resume strategy)
                if step_idx < len(execution.steps_data) and execution.steps_data[step_idx]["status"] == "COMPLETED":
                    logger.info(f"Resume: Skipping already completed step '{service_name}'")
                    cached_response = execution.steps_data[step_idx]["output_response"]
                    responses[service_name] = cached_response
                    cached_payload = execution.steps_data[step_idx]["input_payload"]
                    completed_steps.append((service_name, cached_payload, cached_response))
                    return True, service_name, cached_payload, cached_response, None

                service = ServiceRegistry.get(service_name)
                
                # Evaluate execution condition if defined
                condition = None
                if execution.conditions and isinstance(execution.conditions, dict):
                    condition = execution.conditions.get(service_name)
                
                should_run = True
                if condition:
                    should_run = evaluate_condition(condition, responses, execution.context or {})
                
                if not should_run:
                    step_info = {
                        "service_name": service_name,
                        "status": "SKIPPED",
                        "input_payload": {},
                        "output_response": None,
                        "error_message": "Condition not met",
                        "started_at": datetime.utcnow().isoformat(),
                        "finished_at": datetime.utcnow().isoformat(),
                        "duration_ms": 0,
                        "retry_count": 0
                    }
                    current_steps = list(execution.steps_data)
                    current_steps[step_idx] = step_info
                    execution.steps_data = current_steps
                    db.commit()
                    
                    responses[service_name] = {"success": True, "data": None, "status_code": 200, "skipped": True}
                    return True, service_name, {}, responses[service_name], None

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
                
                # Update steps_data to RUNNING
                current_steps = list(execution.steps_data)
                current_steps[step_idx] = step_info
                execution.steps_data = current_steps
                db.commit()

                # Copy service static inputs
                payload = execution.inputs.get(service_name, {}).copy()

                # Extract optional runtime mock override from input parameters
                mock_override = payload.pop("_mock", None)

                # Resolve incoming mappings from previous service output fields or global context
                for mapping in execution.mappings:
                    if mapping.get("to_service") == service_name:
                        from_service = mapping.get("from_service")
                        val = None
                        
                        if from_service == "context":
                            source_data = execution.context or {}
                            from_field = mapping.get("from_field")
                            val = get_by_path(source_data, from_field)
                        elif from_service in responses:
                            prev_response = responses[from_service]
                            if prev_response.get("success") and prev_response.get("data") is not None:
                                source_data = prev_response["data"]
                                from_field = mapping.get("from_field")
                                val = get_by_path(source_data, from_field)
                                
                        if val is not None:
                            # Apply transformations
                            transform_type = mapping.get("transform")
                            if transform_type == "to_int":
                                try:
                                    val = int(val)
                                except (ValueError, TypeError):
                                    pass
                            elif transform_type == "to_str":
                                val = str(val)
                            elif transform_type == "upper" and isinstance(val, str):
                                val = val.upper()
                            elif transform_type == "lower" and isinstance(val, str):
                                val = val.lower()
                            
                            to_field = mapping.get("to_field")
                            set_by_path(payload, to_field, val)

                step_info["input_payload"] = payload
                current_steps = list(execution.steps_data)
                current_steps[step_idx] = step_info
                execution.steps_data = current_steps
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
                    current_steps = list(execution.steps_data)
                    current_steps[step_idx] = step_info
                    execution.steps_data = current_steps
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
                        # Exponential backoff with Jitter
                        import random
                        backoff = 1.0 * (2 ** (retries - 1))
                        jitter = random.uniform(0.0, 0.5)
                        await asyncio.sleep(backoff + jitter)

                step_info["finished_at"] = datetime.utcnow().isoformat()
                step_info["duration_ms"] = int((time.time() - start_step_time) * 1000)

                if step_success:
                    step_info["status"] = "COMPLETED"
                    step_info["output_response"] = service_response
                    responses[service_name] = service_response
                    
                    # Merge context updates into global execution context state
                    if service_response and isinstance(service_response, dict):
                        context_updates = service_response.get("context_updates")
                        if context_updates and isinstance(context_updates, dict):
                            current_context = dict(execution.context or {})
                            current_context.update(context_updates)
                            execution.context = current_context
                            db.commit()
                else:
                    step_info["status"] = "FAILED"
                    step_info["error_message"] = step_error
                    if service_response:
                        step_info["output_response"] = service_response
                        responses[service_name] = service_response
                    else:
                        responses[service_name] = {
                            "success": False,
                            "data": None,
                            "error": step_error,
                            "status_code": 500
                        }

                current_steps = list(execution.steps_data)
                current_steps[step_idx] = step_info
                execution.steps_data = current_steps
                db.commit()

                return step_success, service_name, payload, service_response or responses[service_name], step_error

            # Helper to execute compensating transaction rollback logic (Saga Pattern)
            async def rollback_sequence(completed_steps_list):
                for name, payload, response in reversed(completed_steps_list):
                    service = ServiceRegistry.get(name)
                    client = APIClient(service_name=service.name, execution_id=execution_id, timeout=service.timeout)
                    try:
                        logger.info(f"SAGA: Running compensating transaction for service '{name}'")
                        await service.compensate(payload=payload, response=response, client=client)
                    except Exception as e:
                        logger.error(f"SAGA: Compensating transaction failed for service '{name}': {e}")

            # Main sequence execution block loop
            flat_idx = 0
            for idx, step_item in enumerate(execution.sequence):
                execution.current_step = idx + 1
                db.commit()

                if isinstance(step_item, list):
                    # Parallel block execution
                    tasks = []
                    for service_name in step_item:
                        tasks.append(run_single_step(service_name, flat_idx))
                        flat_idx += 1
                    
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Process execution results
                    for res in results:
                        if isinstance(res, Exception):
                            raise res
                        
                        step_success, service_name, payload, service_response, step_err = res
                        if not step_success:
                            service = ServiceRegistry.get(service_name)
                            if service.is_critical:
                                # Critical step failed - trigger SAGA rollback
                                execution.status = "FAILED"
                                execution.error_message = f"Failed at critical parallel step {service_name}: {step_err}"
                                # Remove PENDING placeholders to match sequential flow behavior
                                execution.steps_data = [s for s in execution.steps_data if s["status"] != "PENDING"]
                                db.commit()
                                await rollback_sequence(completed_steps)
                                return
                            else:
                                has_partial_failure = True
                        else:
                            completed_steps.append((service_name, payload, service_response))
                else:
                    # Sequential step execution
                    service_name = step_item
                    step_success, service_name, payload, service_response, step_err = await run_single_step(service_name, flat_idx)
                    flat_idx += 1

                    if not step_success:
                        service = ServiceRegistry.get(service_name)
                        if service.is_critical:
                            # Critical step failed - trigger SAGA rollback
                            execution.status = "FAILED"
                            execution.error_message = f"Failed at critical step {service_name}: {step_err}"
                            # Remove PENDING placeholders to match sequential flow behavior
                            execution.steps_data = [s for s in execution.steps_data if s["status"] != "PENDING"]
                            db.commit()
                            await rollback_sequence(completed_steps)
                            return
                        else:
                            has_partial_failure = True
                    else:
                        completed_steps.append((service_name, payload, service_response))

            # Finalize overall execution status
            execution.status = "PARTIAL_SUCCESS" if has_partial_failure else "COMPLETED"
            db.commit()

        except asyncio.CancelledError:
            logger.info(f"Execution {execution_id} was cancelled by user request.")
            try:
                execution = db.query(SequenceExecution).filter(SequenceExecution.id == execution_id).first()
                if execution:
                    execution.status = "FAILED"
                    execution.error_message = "Cancelled by user"
                    execution.steps_data = [s for s in execution.steps_data if s["status"] != "PENDING"]
                    db.commit()
            except Exception:
                pass
            await rollback_sequence(completed_steps)
            raise
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
            cls.active_tasks.pop(execution_id, None)
            try:
                # Re-fetch database object inside a clean scoped session to avoid connection closed error on webhook POST
                db_gen_wh = get_db_session()
                db_wh = next(db_gen_wh)
                try:
                    execution = db_wh.query(SequenceExecution).filter(SequenceExecution.id == execution_id).first()
                    if execution and execution.callback_url:
                        def send_webhook(url: str, payload: dict):
                            try:
                                import requests
                                requests.post(url, json=payload, timeout=5.0)
                            except Exception as err:
                                logger.error(f"Failed to send webhook callback: {err}")
                                
                        payload = {
                            "execution_id": execution.id,
                            "status": execution.status,
                            "error_message": execution.error_message,
                            "context": execution.context,
                            "steps_data": execution.steps_data
                        }
                        loop = asyncio.get_running_loop()
                        loop.run_in_executor(None, send_webhook, execution.callback_url, payload)
                finally:
                    try:
                        next(db_gen_wh)
                    except StopIteration:
                        pass
            except Exception as wh_err:
                logger.error(f"Webhook dispatch system error: {wh_err}")
            finally:
                try:
                    next(db_gen)
                except StopIteration:
                    pass
