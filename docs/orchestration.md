# Orchestration Engine

The **SCF LOS Orchestration Engine** executes sequences of third-party API services asynchronously. It supports sequential and parallel flows, Saga pattern rollbacks, idempotency deduplication, exponential backoff, request timeouts, and credentials resolution.

---

## 1. Architecture Overview

The orchestration workflow consists of:
1. **Trigger API (`POST /api/chain/trigger`)**: Receives the sequence, inputs, mappings, success conditions, and an optional idempotency key.
2. **Orchestrator (`orchestrator.py`)**: Executes steps in a background worker context via FastAPI's `BackgroundTasks`. It parses parallel/sequential steps, applies data mappings, enforces retry limits, and handles failures.
3. **Database Logging**: Execution records are stored in the `sequence_executions` table, and all individual HTTP calls are logged to the `api_logs` table.

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

## 8. Resiliency Features

* **Exponential Backoff and Jitter**: Retries calculate delays dynamically: `delay = (base * 2^(retry_count-1)) + jitter`. This avoids overloading external systems when recovering from outages.
* **Timeout Enforcements**: A default timeout of `10.0` seconds is applied to every client request. Services can customize timeouts by overriding the `timeout` property.
* **Secret Injection**: The engine features a centralized `SecretResolver` in `utils.py` that automatically pulls service credentials from env variables (e.g., `TODO_SERVICE_API_KEY`) and injects them as `Authorization` headers.
