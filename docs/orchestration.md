# Generic Database-Driven Orchestration Engine

The **SCF LOS Orchestration Engine** is a high-performance, asynchronous workflow system powered by **FastAPI** and a dedicated **ARQ (Redis-backed)** job worker (`orchestration-service/`).

---

## 1. Architecture Overview

1. **FastAPI Application**:
   - Exposes developer APIs (`POST /api/standalone/{service_name}`).
   - Automatically detects execution context via `X-Execution-Source` (`standalone` vs `orchestrator`) and `X-Execution-Id`.
   - Exposes sequence recipe configuration CRUD (`/api/sequences`).
   - Exposes named sequence trigger (`POST /api/chain/trigger/{sequence_name}`), status, cancellation, and retries.
2. **Database Recipe Store (`SequenceDefinition`)**:
   - Workflows are defined in the database as JSON recipes specifying the ordered sequence, parameter mappings, branching conditions, and retry assertions.
   - **Zero code changes** to the ARQ orchestrator are required when adding new APIs or workflows.
3. **Standalone Generic ARQ Orchestrator (`orchestration-service/`)**:
   - Executes jobs pulled from Redis asynchronously.
   - Dispatches generic HTTP requests to `POST {FASTAPI_BASE_URL}/api/standalone/{service_name}` with source headers.
   - Automatically caches API tokens for downstream services to avoid repeated auth handshakes.
   - Evaluates dynamic parameter mappings, retry loops with exponential backoff & jitter, and Saga compensations.
4. **Enhanced Status API**:
   - Returns execution status along with `total_tasks`, `completed_tasks`, `pending_tasks`, and a consolidated `responses` dictionary with outputs from each step.

---

## 2. Sequence Execution Control & Syntax

All orchestration control is configured through JSON recipes. Reference configurations are located in `orchestration-service/samples/`.

### A. Linear Sequential Execution
Run tasks one after another, mapping parameters from trigger payload or prior responses:
```json
{
  "name": "user_onboarding_pipeline",
  "sequence": [
    "todo_service",
    "post_service"
  ],
  "mappings": [
    {
      "from_service": "trigger_payload",
      "from_field": "user_id",
      "to_service": "todo_service",
      "to_field": "todo_id"
    },
    {
      "from_service": "todo_service",
      "from_field": "data.title",
      "to_service": "post_service",
      "to_field": "body",
      "transform": "upper"
    }
  ]
}
```

### B. Parallel Execution (Fork-Join)
To run independent tasks concurrently, nest service names inside a sub-list:
```json
{
  "name": "concurrent_kyc_flow",
  "sequence": [
    [
      "todo_service",
      "post_service"
    ]
  ]
}
```

### C. Mixed Parallel & Sequential Barriers
Run sequential steps followed by parallel batches:
```json
{
  "sequence": [
    "todo_service",
    [
      "post_service",
      "credit_service"
    ],
    "notification_service"
  ]
}
```
* `todo_service` runs first.
* `post_service` and `credit_service` execute concurrently in parallel.
* `notification_service` waits for both parallel tasks to complete before executing.

### D. Conditional Branching
Skip tasks dynamically based on previous response data or shared context:
```json
{
  "sequence": ["todo_service", "post_service"],
  "conditions": {
    "post_service": "responses.todo_service.data.completed == True"
  }
}
```

### E. Assertions, Retries & Saga Rollback
```json
{
  "sequence": ["todo_service", "post_service"],
  "success_conditions": {
    "todo_service": {
      "status_codes": [200],
      "body_rules": {
        "success": true
      }
    }
  }
}
```
If a critical service step fails after retries, the orchestrator triggers the **Saga Rollback Pattern**, issuing compensation requests (`POST /api/standalone/{service_name}/compensate`) in reverse order for all completed steps.

---

## 3. Status API Output Example

Calling `GET /api/chain/status/{execution_id}` returns:
```json
{
  "id": "5542fa35-e87f-4db2-a4e0-903ea311bd96",
  "sequence_name": "demo_onboarding_pipeline",
  "status": "COMPLETED",
  "total_tasks": 2,
  "completed_tasks": 2,
  "pending_tasks": 0,
  "responses": {
    "todo_service": {
      "success": true,
      "data": { "id": 15, "title": "ab voluptatum amet" },
      "execution_source": "orchestrator"
    },
    "post_service": {
      "success": true,
      "data": { "id": 101, "title": "Onboarding Result" },
      "execution_source": "orchestrator"
    }
  },
  "steps_data": [
    {
      "service_name": "todo_service",
      "status": "COMPLETED",
      "input_payload": { "todo_id": 15 },
      "output_response": { ... },
      "duration_ms": 636,
      "retry_count": 0
    }
  ]
}
```
