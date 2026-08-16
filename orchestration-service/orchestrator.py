import time
import asyncio
import logging
import httpx
from datetime import datetime
from typing import List, Dict, Any, Optional, Union, Tuple
import redis.asyncio as aioredis
from sqlalchemy.orm import Session
from models import SequenceExecution
from utils import get_by_path, set_by_path
import config
from logger import setup_worker_logger

logger = setup_worker_logger()

class TokenManager:
    """
    Manages JWT Authentication for Orchestrator calls to FastAPI.
    Caches token in Redis with TTL matching token expiry minus safety margin.
    Auto-refreshes token upon expiration.
    """
    _redis_client: Optional[aioredis.Redis] = None

    @classmethod
    async def get_redis(cls) -> aioredis.Redis:
        if cls._redis_client is None:
            cls._redis_client = aioredis.Redis(
                host=config.REDIS_HOST,
                port=config.REDIS_PORT,
                password=config.REDIS_PASSWORD,
                db=config.REDIS_DATABASE,
                decode_responses=True
            )
        return cls._redis_client

    @classmethod
    async def get_bearer_token(cls, http_client: httpx.AsyncClient) -> str:
        try:
            r = await cls.get_redis()
            cached_token = await r.get(config.AUTH_TOKEN_CACHE_KEY)
            if cached_token:
                return cached_token
        except Exception as e:
            logger.warning(f"Redis token cache lookup failed: {e}")

        # Fetch fresh token from FastAPI auth endpoint
        login_url = f"{config.FASTAPI_BASE_URL.rstrip('/')}/api/auth/login"
        payload = {
            "username": config.ORCHESTRATOR_AUTH_USERNAME,
            "password": config.ORCHESTRATOR_AUTH_PASSWORD
        }

        try:
            res = await http_client.post(login_url, json=payload, timeout=10.0)
            if res.status_code == 200:
                data = res.json()
                token = data.get("access_token")
                expires_in = data.get("expires_in_seconds", 3600)
                
                # Cache token in Redis with safety margin (subtract 60s)
                cache_ttl = max(30, expires_in - 60)
                try:
                    r = await cls.get_redis()
                    await r.set(config.AUTH_TOKEN_CACHE_KEY, token, ex=cache_ttl)
                    logger.info(f"Generated and cached new Orchestrator JWT token in Redis (TTL: {cache_ttl}s)")
                except Exception as e:
                    logger.warning(f"Could not cache token in Redis: {e}")
                    
                return token
            else:
                logger.error(f"Failed to authenticate orchestrator against FastAPI at {login_url}: HTTP {res.status_code} {res.text}")
                return ""
        except Exception as e:
            logger.error(f"Exception during orchestrator authentication: {e}")
            return ""

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

def evaluate_success_criteria(
    service_response: Dict[str, Any], 
    criteria: Optional[Dict[str, Any]]
) -> Tuple[bool, Optional[str]]:
    """
    Evaluates customizable success conditions for a service response.
    Supports:
    - expected_status_code (int or list of ints)
    - equals: { "data.status": "APPROVED", ... }
    - not_equals: { "data.is_blacklisted": True, ... }
    - types: { "data.score": "int", "data.user_id": "str", ... }
    """
    if not criteria:
        # Default success check
        if service_response.get("success", True) and service_response.get("status_code", 200) < 400:
            return True, None
        return False, service_response.get("error") or "Service reported failure."

    # 1. Status Code Check
    expected_status = criteria.get("expected_status_code") or criteria.get("status_code")
    actual_status = service_response.get("status_code", 200)
    if expected_status is not None:
        if isinstance(expected_status, list):
            if actual_status not in expected_status:
                return False, f"Expected status code in {expected_status}, got {actual_status}"
        elif actual_status != expected_status:
            return False, f"Expected status code {expected_status}, got {actual_status}"

    # 2. Equality Checks: {"data.status": "COMPLETED"}
    equals_rules = criteria.get("equals") or {}
    for field_path, expected_val in equals_rules.items():
        actual_val = get_by_path(service_response, field_path)
        if actual_val != expected_val:
            return False, f"Field '{field_path}' expected '{expected_val}', got '{actual_val}'"

    # 3. Inequality Checks: {"data.error_flag": True}
    not_equals_rules = criteria.get("not_equals") or {}
    for field_path, unexpected_val in not_equals_rules.items():
        actual_val = get_by_path(service_response, field_path)
        if actual_val == unexpected_val:
            return False, f"Field '{field_path}' must not equal '{unexpected_val}'"

    # 4. Data Type Checks: {"data.id": "int", "data.title": "str"}
    type_rules = criteria.get("types") or {}
    type_map = {
        "int": int,
        "str": str,
        "string": str,
        "float": float,
        "bool": bool,
        "boolean": bool,
        "dict": dict,
        "list": list
    }
    for field_path, expected_type_str in type_rules.items():
        actual_val = get_by_path(service_response, field_path)
        target_type = type_map.get(expected_type_str.lower())
        if target_type and not isinstance(actual_val, target_type):
            return False, f"Field '{field_path}' expected type {expected_type_str}, got {type(actual_val).__name__}"

    return True, None

from typing import Tuple

class Orchestrator:
    """
    Generic, dynamic HTTP-based Orchestrator.
    Dispatches steps to FastAPI standalone endpoints, resolves cascading data mappings,
    handles exponential retries, logs state transitions, and executes Saga rollbacks.
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

        logger.info(f"[TASK_RECEIVED] Execution {execution_id} received by ARQ Orchestrator.")

        try:
            execution = db.query(SequenceExecution).filter(SequenceExecution.id == execution_id).first()
            if not execution:
                logger.error(f"[TASK_ERROR] Execution {execution_id} not found in database.")
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
            else:
                # If resuming an existing execution, populate prior successful responses
                for step in execution.steps_data:
                    if step.get("status") == "COMPLETED" and step.get("output_response"):
                        s_name = step["service_name"]
                        responses[s_name] = step["output_response"]
                        completed_steps.append((s_name, step.get("input_payload", {}), step["output_response"]))

            # Step Execution Worker
            async def run_single_step(service_name: str, step_idx: int):
                step_info = execution.steps_data[step_idx]
                if step_info.get("status") == "COMPLETED":
                    logger.info(f"[TASK_STEP_SKIPPED] Step {step_idx + 1} ({service_name}) already completed previously. Skipping.")
                    return True, service_name, step_info.get("input_payload", {}), step_info.get("output_response", {}), None, True

                # Evaluate conditional skip expressions
                conditions_dict = execution.conditions or {}
                condition_expr = conditions_dict.get(service_name)
                if condition_expr and not evaluate_condition(condition_expr, responses, execution.context or {}):
                    logger.info(f"[TASK_STEP_SKIPPED] Condition '{condition_expr}' evaluated to False for service '{service_name}'.")
                    updated_step = dict(execution.steps_data[step_idx])
                    updated_step["status"] = "SKIPPED"
                    updated_step["error_message"] = "Condition evaluated to False"
                    current_steps = [dict(s) for s in execution.steps_data]
                    current_steps[step_idx] = updated_step
                    execution.steps_data = current_steps
                    db.commit()
                    return True, service_name, {}, None, None, False

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

                # Start with base inputs for this service
                payload = execution.inputs.get(service_name, {}).copy()

                # ------------------------------------------------------------------
                # Dynamic Parameter Mapping across Trigger Payload & Prior Services
                # Supports:
                # 1. from_service == "trigger_payload" -> from execution.trigger_payload
                # 2. from_service in responses -> from responses[from_service] (or responses[from_service].data)
                # 3. from_service == "context" -> from execution.context
                # ------------------------------------------------------------------
                for mapping in (execution.mappings or []):
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
                            # Check top-level response or nested 'data' dictionary
                            val = get_by_path(prev_response, from_field)
                            if val is None and isinstance(prev_response, dict) and "data" in prev_response:
                                val = get_by_path(prev_response["data"], from_field)
                                
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

                # Execute HTTP call to FastAPI with Bearer Token & Exponential Retries
                retries = 0
                max_retries = 3
                step_success = False
                service_response = None
                step_error = None
                is_critical = True
                start_step_time = time.time()
                endpoint_url = f"{config.FASTAPI_BASE_URL.rstrip('/')}/api/standalone/{service_name}"

                custom_criteria = (execution.success_conditions or {}).get(service_name)

                while retries <= max_retries:
                    step_info["retry_count"] = retries
                    current_steps = list(execution.steps_data)
                    current_steps[step_idx] = step_info
                    execution.steps_data = current_steps
                    db.commit()

                    # Retrieve cached or refreshed JWT Bearer Token
                    token = await TokenManager.get_bearer_token(http_client)
                    headers = {
                        "X-Execution-Source": "orchestrator",
                        "X-Execution-Id": execution_id
                    }
                    if token:
                        headers["Authorization"] = f"Bearer {token}"

                    if retries > 0:
                        logger.warning(f"[TASK_RETRY] Retry attempt {retries}/{max_retries} for step '{service_name}' (Execution: {execution_id})")

                    try:
                        resp = await http_client.post(endpoint_url, json=payload, headers=headers)
                        try:
                            resp_data = resp.json()
                        except Exception:
                            resp_data = {"text": resp.text, "status_code": resp.status_code}

                        if isinstance(resp_data, dict) and "status_code" not in resp_data:
                            resp_data["status_code"] = resp.status_code

                        # Evaluate success based on HTTP status and customizable criteria
                        is_ok, err_msg = evaluate_success_criteria(resp_data, custom_criteria)
                        if is_ok and 200 <= resp.status_code < 300:
                            step_success = True
                            service_response = resp_data
                            break
                        else:
                            step_error = err_msg or resp_data.get("detail") or resp_data.get("error") or f"HTTP {resp.status_code}"
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
                    logger.info(f"[TASK_STEP_SUCCESS] Step {step_idx + 1} ({service_name}) completed successfully in {step_info['duration_ms']}ms.")
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
                    logger.error(f"[TASK_STEP_FAILED] Step {step_idx + 1} ({service_name}) failed after {retries - 1} retries. Error: {step_error}")
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
                token = await TokenManager.get_bearer_token(http_client)
                headers = {"X-Execution-Id": execution_id}
                if token:
                    headers["Authorization"] = f"Bearer {token}"

                for name, payload_data, response_data in reversed(completed_steps_list):
                    compensate_url = f"{config.FASTAPI_BASE_URL.rstrip('/')}/api/standalone/{name}/compensate"
                    try:
                        logger.info(f"SAGA: Calling compensation for service '{name}' at {compensate_url}")
                        await http_client.post(
                            compensate_url,
                            json={"input_payload": payload_data, "output_response": response_data},
                            headers=headers
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
                                logger.error(f"[TASK_FAILED] Sequence {execution_id} marked as FAILED at step '{service_name}'. Initiating rollback.")
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
                            logger.error(f"[TASK_FAILED] Sequence {execution_id} marked as FAILED at step '{service_name}'. Initiating rollback.")
                            await rollback_sequence(completed_steps)
                            return
                        else:
                            has_partial_failure = True
                    else:
                        completed_steps.append((service_name, payload_data, service_resp))

            final_status = "PARTIAL_SUCCESS" if has_partial_failure else "COMPLETED"
            execution.status = final_status
            db.commit()
            logger.info(f"[TASK_SUCCESS] Execution {execution_id} finished with status '{final_status}'.")

        except asyncio.CancelledError:
            logger.info(f"[TASK_CANCELLED] Execution {execution_id} cancelled.")
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
            logger.exception(f"[TASK_ERROR] Orchestrator internal failure for execution {execution_id}: {e}")
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
