# Orchestration Engine

The **SCF LOS Orchestration Engine** executes sequences of third-party API services asynchronously. It supports sequential and parallel flows, Saga pattern rollbacks, idempotency deduplication, exponential backoff, request timeouts, and credentials resolution.

---

## 1. Architecture Overview

The orchestration workflow consists of:
1. **Trigger API (`POST /api/chain/trigger`)**: Receives the sequence, inputs, mappings, success conditions, and an optional idempotency key.
2. **Orchestrator (`orchestrator.py`)**: Executes steps in a background worker context via FastAPI's `BackgroundTasks`. It parses parallel/sequential steps, applies data mappings, enforces retry limits, and handles failures.
3. **Database Logging**: Execution records are stored in the `sequence_executions` table, and all individual HTTP calls are logged to the `api_logs` table.

### Database Schema Details (`SequenceExecution`)
* `id` (String UUID): Primary key.
* `sequence` (JSON): The ordered list of service names.
* `inputs` (JSON): Dict mapping service names to initial payload arguments.
* `mappings` (JSON): Declared field mapping instructions.
* `success_conditions` (JSON): Assert rules evaluating output status/body values.
* `conditions` (JSON): Conditional rules to run or skip execution steps.
* `context` (JSON): Dynamic shared global state dict.
* `callback_url` (String): Address to dispatch webhook POST callbacks.
* `idempotency_key` (String): Key verifying unique submissions.
* `status` (String): Workflow state (`PENDING`, `RUNNING`, `COMPLETED`, `PARTIAL_SUCCESS`, `FAILED`).
* `current_step` (Integer): Step index currently running.
* `steps_data` (JSON): Execution trace list containing timestamps, durations, and outputs.
* `error_message` (String): Failure reason populated on exceptions.

---

## 2. Parallel Execution (Fork-Join)

To run multiple steps concurrently, nest their names in a sub-list within the `sequence` payload:
```json
{
    "sequence": [
        "todo_service",
        ["post_service", "another_service"]
    ]
}
```
*In this sequence:*
1. `todo_service` runs sequentially.
2. `post_service` and `another_service` execute concurrently using `asyncio.gather()`.

> [!NOTE]
> Services in a parallel block execute concurrently, meaning they cannot map data from one another. They can only map from steps that completed *before* the parallel block started.

---

## 3. Saga Pattern (Rollback Compensations)

If a critical step fails (e.g. downstream service error or maximum retries exceeded), the orchestrator transitions to the `FAILED` status and automatically rolls back all previously successfully completed steps in **reverse order**.

* Each service class implements its own rollback logic inside the `compensate` method:
  ```python
  async def compensate(self, payload: Dict[str, Any], response: Dict[str, Any], client: APIClient) -> None:
      # e.g., perform a DELETE request to undo the resource creation
  ```

---

## 4. Idempotency & Deduplication

To prevent duplicate runs (e.g. from network retries), pass a unique `idempotency_key` string:
```json
{
    "sequence": ["todo_service"],
    "inputs": {"todo_service": {"todo_id": 1}},
    "idempotency_key": "unique-uuid-123456"
}
```
* If a duplicate key is detected, the API returns the existing record immediately.
* If the task is already `RUNNING` or `COMPLETED`, it will not launch a duplicate background task.

---

## 5. Conditional Step Routing

You can conditionally run or skip individual steps by defining python-based boolean expressions in the `conditions` object mapping `service_name -> expression`:
```json
{
    "sequence": ["todo_service", "post_service"],
    "conditions": {
        "post_service": "responses.todo_service.data.completed == True"
    }
}
```
* **Evaluation Context**: The evaluator exposes two root namespaces to your condition expression:
  * `responses`: A dot-accessible object of previous service responses (e.g., `responses.todo_service.data.completed`).
  * `context`: A dot-accessible object of the global shared context (e.g., `context.is_vip`).
* **Behavior**: If the condition evaluates to `False`, the step is marked as `SKIPPED` in the database, and the execution proceeds cleanly to the next step.

---

## 6. Mapping Transformations

When passing outputs to inputs, you can specify an optional `transform` type in the mapping payload to convert or modify values:
```json
{
    "mappings": [
        {
            "from_service": "todo_service",
            "from_field": "id",
            "to_service": "post_service",
            "to_field": "todo_id",
            "transform": "to_int"
        }
    ]
}
```
Supported transformation types:
* `to_int`: Converts values to integers (e.g., `"123"` $\rightarrow$ `123`).
* `to_str`: Converts values to strings (e.g., `123` $\rightarrow$ `"123"`).
* `upper`: Converts string values to UPPERCASE.
* `lower`: Converts string values to lowercase.

---

## 7. Global Shared Context (State Management)

You can pass a global `context` dictionary at trigger time and map fields from it directly into target service payloads. Additionally, services can update this context dynamically at runtime.

### Mapping from Global Context
Use `"context"` as the `from_service` name in your mappings:
```json
{
    "context": {
        "user_tier": "VIP"
    },
    "mappings": [
        {
            "from_service": "context",
            "from_field": "user_tier",
            "to_service": "post_service",
            "to_field": "priority"
        }
    ]
}
```

### Runtime Context Updates
A service subclass can modify the global context dynamically by returning a `context_updates` dictionary in its execution response:
```python
async def _run(self, payload: dict, client: APIClient):
    # Service execution...
    return {
        "success": True,
        "data": {"result": "success"},
        "context_updates": {
            "credit_decision": "APPROVED"
        }
    }
```
The orchestrator automatically updates the execution's persistent context state with these updates as they occur.

---

## 8. Webhook Callback Notifications

You can pass a `callback_url` parameter in your trigger payload:
```json
{
    "sequence": ["todo_service"],
    "callback_url": "https://your.webhook.domain/callbacks"
}
```
When the sequence completes (either successfully, with partial success, or fails with an error/cancellation), the orchestrator automatically triggers a non-blocking `POST` notification back to that URL.

### Webhook Dispatch Code Implementation
Webhooks are dispatched inside the `finally` block of the orchestrator's sequence loop. To prevent slow downstream listeners from blocking the orchestrator's event loop, the callback POST request is offloaded to a thread pool executor:
```python
# Inside orchestrator.py: run_sequence
finally:
    # Remove from active tasks tracking registry
    Orchestrator.active_tasks.pop(execution_id, None)
    
    if execution.callback_url:
        callback_payload = {
            "execution_id": execution.id,
            "status": execution.status,
            "error_message": execution.error_message,
            "context": execution.context,
            "steps_data": execution.steps_data
        }
        try:
            logger.info(f"Dispatching webhook notification to: {execution.callback_url}")
            loop = asyncio.get_running_loop()
            # Non-blocking dispatch to thread pool
            loop.run_in_executor(
                None,
                lambda: requests.post(
                    execution.callback_url, 
                    json=callback_payload, 
                    headers={"Content-Type": "application/json"},
                    timeout=5.0
                )
            )
        except Exception as e:
            logger.error(f"Failed to dispatch webhook callback callback: {e}")
```

---

## 9. Graceful Cancellation & Aborts

If you need to stop an active execution, call the cancel endpoint:
* **Endpoint**: `POST /api/chain/cancel/{execution_id}`
* **Behavior**:
  * Aborts the background task immediately using native asyncio cancellation.
  * Sets the execution status in the database to `FAILED` with the message `"Cancelled by user"`.
  * Automatically triggers SAGA rollbacks (`compensate` calls) for all previously completed steps in reverse order to return systems to a consistent state.

### Cancellation & SAGA Rollback Code Implementation
When a cancellation request is received, the background task is resolved from the memory map and `.cancel()` is invoked, raising an `asyncio.CancelledError` inside the worker loop. The orchestrator catches this error and rolls back completed steps:
```python
# Register active task in memory registry:
Orchestrator.active_tasks[execution_id] = asyncio.current_task()

try:
    # Run sequence steps loop...
    for step_idx, step_item in enumerate(execution.sequence):
        # ...
        
except asyncio.CancelledError:
    logger.warning(f"Orchestration sequence '{execution_id}' cancelled by user. Rolling back completed steps...")
    # Rollback completed steps in reverse order (SAGA Compensating Transactions)
    for name, payload, response in reversed(completed_steps):
        try:
            service = ServiceRegistry.get(name)
            client = APIClient(service_name=service.name, execution_id=execution_id, timeout=service.timeout)
            logger.info(f"Running compensating transaction for service: {name}")
            await service.compensate(payload=payload, response=response, client=client)
        except Exception as comp_err:
            logger.error(f"Saga compensation failed for service '{name}': {comp_err}")
    
    # Save cancelled state to DB
    execution.status = "FAILED"
    execution.error_message = "Cancelled by user"
    db.commit()
    raise  # Propagate cancellation to cleanly terminate task
```

---

## 10. Sequence Retry / Resume

If a sequence failed, you can retry it using one of two strategy profiles:
* **Endpoint**: `POST /api/chain/retry/{execution_id}`
* **Payload**:
  ```json
  {
      "strategy": "restart"
  }
  ```
  *(or `"strategy": "resume"`)*
* **Strategies**:
  * `restart`: Clears all past run logs (`steps_data`), resets step counts to 0, and runs the entire orchestration sequence from scratch.
  * `resume`: Preserves already completed tasks in the previous failed run, sets the failed steps back to `"PENDING"`, and starts executing from the first failed step forward (avoiding double-billing on upstream APIs).

### Resume Cache Code Implementation
When resuming an execution, the orchestrator loops over all step indices. For each step, it checks the cached state in the database. If the step is already marked `COMPLETED`, the service call is skipped, and results are loaded from the cache:
```python
# Inside orchestrator.py: run_single_step
async def run_single_step(service_name: str, step_idx: int):
    # Check if this step is already completed from a previous run (Resume strategy)
    if step_idx < len(execution.steps_data) and execution.steps_data[step_idx]["status"] == "COMPLETED":
        logger.info(f"Resume: Skipping already completed step '{service_name}'")
        cached_response = execution.steps_data[step_idx]["output_response"]
        responses[service_name] = cached_response
        cached_payload = execution.steps_data[step_idx]["input_payload"]
        
        # Track in completed steps array (so that it can be rolled back if a later step fails)
        completed_steps.append((service_name, cached_payload, cached_response))
        return True, service_name, cached_payload, cached_response, None

    # Otherwise, execute service as normal...
    service = ServiceRegistry.get(service_name)
```

---

## 11. Resiliency Features

* **Lifespan Startup Recovery (Crash Resilience)**: FastAPI's startup hook (`lifespan`) automatically scans the database for any sequence execution marked as `PENDING` or `RUNNING` (which indicates it was interrupted by a server restart or crash). To support multi-instance deployments (load-balanced/autoscaled pods) without duplicating background tasks, workers execute an atomic distributed query claiming tasks using a unique `worker_id` stored inside the `error_message` field. Only the worker that successfully claims a task executes it.
* **Exponential Backoff and Jitter**: Retries calculate delays dynamically: `delay = (base * 2^(retry_count-1)) + jitter`. This avoids overloading external systems when recovering from outages.
* **Timeout Enforcements**: A default timeout of `10.0` seconds is applied to every client request. Services can customize timeouts by overriding the `timeout` property.
* **Secret Injection**: The engine features a centralized `SecretResolver` in `utils.py` that automatically pulls service credentials from env variables (e.g., `TODO_SERVICE_API_KEY`) and injects them as `Authorization` headers.

### Distributed Lifespan Recovery Code Implementation
The recovery mechanism is registered in the main application lifecycle startup process. It relies on SQL atomic writes to prevent concurrent workers from claiming the same orphaned runs:
```python
# Inside main.py:
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup Recovery: Detect and resume pending/running executions that were interrupted.
    # To prevent race conditions in multi-instance deployments, we atomically claim tasks using a unique worker ID.
    import uuid
    worker_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        # Atomically claim any unclaimed PENDING or RUNNING task for this worker instance in a single write operation
        db.query(SequenceExecution).filter(
            SequenceExecution.status.in_(["PENDING", "RUNNING"]),
            (SequenceExecution.error_message == None) | (~SequenceExecution.error_message.like("Recovering:%"))
        ).update(
            {
                SequenceExecution.status: "PENDING",
                SequenceExecution.error_message: f"Recovering:{worker_id}"
            },
            synchronize_session=False
        )
        db.commit()

        # Query only the tasks successfully claimed by this worker
        claimed_runs = db.query(SequenceExecution).filter(
            SequenceExecution.error_message == f"Recovering:{worker_id}"
        ).all()

        if claimed_runs:
            logger.info(f"Startup: Worker {worker_id} claimed {len(claimed_runs)} interrupted sequence executions. Resuming...")
            for execution in claimed_runs:
                # Spawn non-blocking background task to resume execution.
                # error_message is kept as 'Recovering:{worker_id}' to serve as an active claim indicator.
                asyncio.create_task(Orchestrator.run_sequence(execution.id, lambda: SessionLocal()))
    except Exception as e:
        logger.error(f"Startup: Failed to recover interrupted tasks: {e}")
    finally:
        db.close()
    yield
```
