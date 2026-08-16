# Generic Database-Driven Orchestration Engine

The **SCF LOS Orchestration Engine** is a high-performance, asynchronous workflow system powered by **FastAPI** (`los-app/`) and a dedicated **ARQ (Redis-backed)** job worker (`orchestration-service/`).

---

## 1. Architecture Overview

1. **FastAPI Application**:
   - Exposes developer standalone APIs (`POST /api/standalone/{service_name}`).
   - Automatically detects execution context via `X-Execution-Source` (`standalone` vs `orchestrator`) and `X-Execution-Id`.
   - Exposes sequence recipe configuration CRUD (`/api/sequences`) - **Admin Only**.
   - Exposes named sequence trigger (`POST /api/chain/trigger/{sequence_name}`), returning `{ "task_id": "...", "task_name": "..." }`.
   - Supports resuming failed tasks from point of failure via `previous_task_id`.
2. **Database Recipe Store (`SequenceDefinition`)**:
   - Workflows are defined in PostgreSQL/SQLite as JSON recipes specifying the ordered sequence, cascading parameter mappings, branching conditions, skip rules, and customizable success assertions.
   - **Zero code changes** to the ARQ orchestrator are required when adding new APIs or workflows.
3. **Generic ARQ Orchestrator (`orchestration-service/`)**:
   - Executes jobs pulled from Redis asynchronously.
   - Handles auto-refreshing JWT token management cached in Redis (`los:orchestrator:jwt_token`).
   - Dispatches HTTP requests to `POST {FASTAPI_BASE_URL}/api/standalone/{service_name}` with source headers.
   - Evaluates dynamic parameter mappings, exponential backoff retries with jitter, and Saga compensations.
4. **Enhanced Status API**:
   - Returns execution status along with `total_tasks`, `completed_tasks`, `pending_tasks`, and a consolidated `responses` dictionary with outputs from each step.

---

## 2. Integrated Services (JSONPlaceholder Real REST API)

The platform provides 3 real non-mocked REST integration services:

1. **`create_post_service`**:
   - Creates a new post via `POST https://jsonplaceholder.typicode.com/posts`.
   - Input parameters: `title`, `body`, `userId`.
   - Response: `{ "success": true, "data": { "id": 101, "title": "...", "body": "...", "userId": ... }, "status_code": 201 }`.
   - Compensation: `DELETE https://jsonplaceholder.typicode.com/posts/{id}`.

2. **`get_post_service`**:
   - Retrieves a post by ID via `GET https://jsonplaceholder.typicode.com/posts/{post_id}`.
   - Input parameters: `post_id` (or `id`).
   - Response: `{ "success": true, "data": { "id": ..., "title": "...", "body": "..." }, "status_code": 200 }`.

3. **`update_post_service`**:
   - Updates an existing post via `PUT https://jsonplaceholder.typicode.com/posts/{id}`.
   - Input parameters: `id` (or `post_id`), `title`, `body`, `userId`.
   - Response: `{ "success": true, "data": { "id": ..., "title": "...", "body": "..." }, "status_code": 200 }`.

---

## 3. End-to-End Post Lifecycle Sequence Recipe

A complete workflow testing creation, retrieval, modification, and verification without mocks:

```json
{
  "name": "jsonplaceholder_post_lifecycle_pipeline",
  "description": "Lifecycle pipeline: 1. Create post -> 2. Get post by id -> 3. Update post (PUT) -> 4. Get updated post",
  "sequence": [
    "create_post_service",
    "get_post_service",
    "update_post_service",
    "get_post_service"
  ],
  "default_inputs": {
    "create_post_service": { "userId": 1 },
    "get_post_service": {},
    "update_post_service": { "userId": 1 }
  },
  "mappings": [
    {
      "from_service": "trigger_payload",
      "from_field": "post_title",
      "to_service": "create_post_service",
      "to_field": "title"
    },
    {
      "from_service": "trigger_payload",
      "from_field": "post_body",
      "to_service": "create_post_service",
      "to_field": "body"
    },
    {
      "from_service": "create_post_service",
      "from_field": "data.id",
      "to_service": "get_post_service",
      "to_field": "post_id"
    },
    {
      "from_service": "create_post_service",
      "from_field": "data.id",
      "to_service": "update_post_service",
      "to_field": "id"
    },
    {
      "from_service": "trigger_payload",
      "from_field": "update_title",
      "to_service": "update_post_service",
      "to_field": "title"
    },
    {
      "from_service": "trigger_payload",
      "from_field": "update_body",
      "to_service": "update_post_service",
      "to_field": "body"
    }
  ],
  "success_conditions": {
    "create_post_service": {
      "expected_status_code": [200, 201],
      "equals": { "success": true },
      "types": { "data.id": "int" }
    },
    "get_post_service": {
      "expected_status_code": 200,
      "equals": { "success": true }
    },
    "update_post_service": {
      "expected_status_code": 200,
      "equals": { "success": true }
    }
  },
  "skip_conditions": [
    {
      "service": "update_post_service",
      "condition": "context.skip_update == True",
      "reason": "Update skipped as per context flag"
    }
  ]
}
```

---

## 4. Conditional Step Skipping (`skip_conditions`)

The orchestrator supports skipping steps dynamically by specifying `skip_conditions` as a list of rules in the sequence JSON recipe:

```json
"skip_conditions": [
  {
    "service": "update_post_service",
    "condition": "responses.create_post_service.data.id > 100",
    "reason": "Skip update step for mock post IDs"
  },
  {
    "service": "get_post_service",
    "condition": "context.skip_verification == True",
    "reason": "Verification disabled"
  }
]
```
When a condition evaluates to `True`, the worker marks the step as `SKIPPED`, logs the reason, and advances immediately to the next task in the workflow.

---

## 5. Triggering & Resuming Execution

### Triggering a Sequence
```http
POST /api/chain/trigger/jsonplaceholder_post_lifecycle_pipeline
Authorization: Bearer <client_token>
Content-Type: application/json

{
  "payload": {
    "post_title": "My Orchestrated Post",
    "post_body": "Created via SCF LOS workflow engine",
    "update_title": "My Updated Post Title",
    "update_body": "Updated via PUT step"
  }
}
```
**Response:**
```json
{
  "task_id": "847df317-a068-45b6-bf25-cc742a78bf29",
  "task_name": "jsonplaceholder_post_lifecycle_pipeline"
}
```

### Resuming Failed Execution from Point of Failure
```http
POST /api/chain/trigger/jsonplaceholder_post_lifecycle_pipeline
Authorization: Bearer <client_token>
Content-Type: application/json

{
  "payload": { ... },
  "previous_task_id": "847df317-a068-45b6-bf25-cc742a78bf29"
}
```
If `previous_task_id` is supplied, all previously completed steps and responses are retained, and execution picks up from the failed step.
