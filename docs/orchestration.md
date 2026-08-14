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

### Callback Payload JSON Schema:
```json
{
    "execution_id": "4b54e7d4-8d48-43d9-a790-db0776bdf2db",
    "status": "COMPLETED",
    "error_message": null,
    "context": {
        "client_type": "premium",
        "credit_decision": "APPROVED"
    },
    "steps_data": [
        {
            "service_name": "todo_service",
            "status": "COMPLETED",
            "input_payload": {
                "todo_id": 2
            },
            "output_response": {
                "success": true,
                "data": {
                    "userId": 1,
                    "id": 2,
                    "title": "quis ut nam facilis et officia qui",
                    "completed": true
                },
                "error": null,
                "status_code": 200
            },
            "error_message": null,
            "started_at": "2026-08-14T03:57:07.123456",
            "finished_at": "2026-08-14T03:57:07.234567",
            "duration_ms": 111,
            "retry_count": 0
        }
    ]
}
```

---

## 9. Graceful Cancellation & Aborts

If you need to stop an active execution, call the cancel endpoint:
* **Endpoint**: `POST /api/chain/cancel/{execution_id}`
* **Behavior**:
  * Aborts the background task immediately using native asyncio cancellation.
  * Sets the execution status in the database to `FAILED` with the message `"Cancelled by user"`.
  * Automatically triggers SAGA rollbacks (`compensate` calls) for all previously completed steps in reverse order to return systems to a consistent state.

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

---

## 11. Resiliency Features

* **Exponential Backoff and Jitter**: Retries calculate delays dynamically: `delay = (base * 2^(retry_count-1)) + jitter`. This avoids overloading external systems when recovering from outages.
* **Timeout Enforcements**: A default timeout of `10.0` seconds is applied to every client request. Services can customize timeouts by overriding the `timeout` property.
* **Secret Injection**: The engine features a centralized `SecretResolver` in `utils.py` that automatically pulls service credentials from env variables (e.g., `TODO_SERVICE_API_KEY`) and injects them as `Authorization` headers.
