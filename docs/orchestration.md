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
* If the task is already `RUNNING` or `COMPLETED`, it will not launch a duplicate background task, protecting downstream systems from redundant API costs.

---

## 5. Resiliency Features

* **Exponential Backoff and Jitter**: Retries calculate delays dynamically: `delay = (base * 2^(retry_count-1)) + jitter`. This avoids overloading external systems when recovering from outages.
* **Timeout Enforcements**: A default timeout of `10.0` seconds is applied to every client request. Services can customize timeouts by overriding the `timeout` property:
  ```python
  @property
  def timeout(self) -> float:
      return 5.0 # 5 seconds
  ```
* **Secret Injection**: The engine features a centralized `SecretResolver` in `utils.py` that automatically pulls service credentials from env variables (e.g., `TODO_SERVICE_API_KEY`) and injects them as `Authorization` headers.

---

## 6. Inter-Service Data Mapping

To pass outputs from a previous API as inputs to the next API in a sequence, define mappings in the `mappings` list of your trigger payload.

### Mapping Rule Syntax
Each mapping rule is an object:
* `from_service`: The name of the source service (e.g. `"todo_service"`).
* `from_field`: The dot-notated path to resolve inside the source service's **response data block** (`response["data"]`).
* `to_service`: The name of the target service (e.g. `"post_service"`).
* `to_field`: The dot-notated path in the target service's input payload to populate.

#### Example Payload:
```json
{
    "sequence": [
        "todo_service",
        "post_service"
    ],
    "inputs": {
        "todo_service": {
            "todo_id": 2
        },
        "post_service": {
            "body": "Static post description"
        }
    },
    "mappings": [
        {
            "from_service": "todo_service",
            "from_field": "title",
            "to_service": "post_service",
            "to_field": "title"
        }
    ]
}
```
