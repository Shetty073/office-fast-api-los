import time
import asyncio
import logging
import httpx
from datetime import datetime
from typing import List, Dict, Any, Optional, Union
from sqlalchemy.orm import Session
from models import SequenceExecution
from utils import get_by_path, set_by_path
import config

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
    """
    Generic, dynamic HTTP-based Orchestrator.
    Dispatches steps to FastAPI standalone endpoints, evaluates data mappings,
    handles exponential retries, and executes Saga rollbacks.
    """
    active_tasks: Dict[str, asyncio.Task] = {}

    @classmethod
    async def run_sequence(cls, execution_id: str, get_db_session, http_client: Optional[httpx.AsyncClient] = None):
        cls.active_tasks[execution_id] = asyncio.current_task()
        db_gen = get_db_session()
        db = next(db_gen)
        
        should_close_client = False
        if http_client is None:
            http_client = httpx.AsyncClient(timeout=30.0)
            should_close_client = True

        try:
            execution = db.query(SequenceExecution).filter(SequenceExecution.id == execution_id).first()
            if not execution:
                logger.error(f"Execution {execution_id} not found.")
                return

            execution.status = "RUNNING"
            db.commit()

            responses: Dict[str, Dict[str, Any]] = {}
            completed_steps = []  # Tuples: (service_name, input_payload, output_response)
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

            # Helper for executing a single step over HTTP to FastAPI
            async def run_single_step(service_name: str, step_idx: int):
                # Resume strategy check
                if step_idx < len(execution.steps_data) and execution.steps_data[step_idx]["status"] == "COMPLETED":
                    logger.info(f"Resume: Skipping already completed step '{service_name}'")
                    cached_response = execution.steps_data[step_idx]["output_response"]
                    responses[service_name] = cached_response
                    cached_payload = execution.steps_data[step_idx]["input_payload"]
                    completed_steps.append((service_name, cached_payload, cached_response))
                    return True, service_name, cached_payload, cached_response, None, True

                # Evaluate execution condition
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
                    return True, service_name, {}, responses[service_name], None, True

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
                current_steps = list(execution.steps_data)
                current_steps[step_idx] = step_info
                execution.steps_data = current_steps
                db.commit()

                # Start with static inputs for this service
                payload = execution.inputs.get(service_name, {}).copy()

                # Dynamic parameter mapping from trigger_payload, context, or previous step outputs
                for mapping in execution.mappings:
                    if mapping.get("to_service") == service_name:
                        from_service = mapping.get("from_service")
                        from_field = mapping.get("from_field")
                        val = None
                        
                        if from_service == "trigger_payload":
                            trigger_data = execution.trigger_payload or {}
                            val = get_by_path(trigger_data, from_field)
                        elif from_service == "context":
                            source_data = execution.context or {}
                            val = get_by_path(source_data, from_field)
                        elif from_service in responses:
                            prev_response = responses[from_service]
                            if prev_response.get("success") and prev_response.get("data") is not None:
                                source_data = prev_response["data"]
                                val = get_by_path(source_data, from_field)
                                
                        if val is not None:
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

                # Execute HTTP call to FastAPI with retries & backoff
                retries = 0
                max_retries = 3
                step_success = False
                service_response = None
                step_error = None
                is_critical = True
                start_step_time = time.time()
                endpoint_url = f"{config.FASTAPI_BASE_URL.rstrip('/')}/api/standalone/{service_name}"

                headers = {
                    "X-Execution-Source": "orchestrator",
                    "X-Execution-Id": execution_id
                }

                while retries <= max_retries:
                    step_info["retry_count"] = retries
                    current_steps = list(execution.steps_data)
                    current_steps[step_idx] = step_info
                    execution.steps_data = current_steps
                    db.commit()

                    try:
                        resp = await http_client.post(endpoint_url, json=payload, headers=headers)
                        try:
                            resp_data = resp.json()
                        except Exception:
                            resp_data = {"text": resp.text}

                        if 200 <= resp.status_code < 300 and resp_data.get("success", True):
                            step_success = True
                            service_response = resp_data
                            break
                        else:
                            step_error = resp_data.get("detail") or resp_data.get("error") or f"HTTP {resp.status_code}"
                            service_response = resp_data
                    except Exception as e:
                        step_error = str(e)

                    retries += 1
                    if retries <= max_retries:
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
                    
                    # Merge context updates
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
                    step_info["output_response"] = service_response
                    responses[service_name] = service_response or {
                        "success": False,
                        "error": step_error,
                        "status_code": 500
                    }

                current_steps = list(execution.steps_data)
                current_steps[step_idx] = step_info
                execution.steps_data = current_steps
                db.commit()

                return step_success, service_name, payload, responses[service_name], step_error, is_critical

            # Saga Rollback compensation helper
            async def rollback_sequence(completed_steps_list):
                for name, payload_data, response_data in reversed(completed_steps_list):
                    compensate_url = f"{config.FASTAPI_BASE_URL.rstrip('/')}/api/standalone/{name}/compensate"
                    try:
                        logger.info(f"SAGA: Calling compensation for service '{name}' at {compensate_url}")
                        await http_client.post(
                            compensate_url,
                            json={"input_payload": payload_data, "output_response": response_data},
                            headers={"X-Execution-Id": execution_id}
                        )
                    except Exception as e:
                        logger.error(f"SAGA: Compensation failed for service '{name}': {e}")

            # Main sequence loop
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
                    for res in results:
                        if isinstance(res, Exception):
                            raise res
                        
                        step_success, service_name, payload_data, service_resp, step_err, is_crit = res
                        if not step_success:
                            if is_crit:
                                execution.status = "FAILED"
                                execution.error_message = f"Failed at critical step {service_name}: {step_err}"
                                execution.steps_data = [s for s in execution.steps_data if s["status"] != "PENDING"]
                                db.commit()
                                await rollback_sequence(completed_steps)
                                return
                            else:
                                has_partial_failure = True
                        else:
                            completed_steps.append((service_name, payload_data, service_resp))
                else:
                    service_name = step_item
                    step_success, service_name, payload_data, service_resp, step_err, is_crit = await run_single_step(service_name, flat_idx)
                    flat_idx += 1

                    if not step_success:
                        if is_crit:
                            execution.status = "FAILED"
                            execution.error_message = f"Failed at critical step {service_name}: {step_err}"
                            execution.steps_data = [s for s in execution.steps_data if s["status"] != "PENDING"]
                            db.commit()
                            await rollback_sequence(completed_steps)
                            return
                        else:
                            has_partial_failure = True
                    else:
                        completed_steps.append((service_name, payload_data, service_resp))

            execution.status = "PARTIAL_SUCCESS" if has_partial_failure else "COMPLETED"
            db.commit()

        except asyncio.CancelledError:
            logger.info(f"Execution {execution_id} cancelled.")
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
            logger.exception(f"Orchestrator internal failure: {e}")
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
            if should_close_client and http_client:
                await http_client.aclose()
            try:
                next(db_gen)
            except StopIteration:
                pass
