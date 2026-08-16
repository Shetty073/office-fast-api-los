# Orchestration Service (`orchestration-service`) Developer Guide

The **ARQ Orchestration Service** is a dedicated, asynchronous background execution worker. It is decoupled from the FastAPI web tier and communicates with it entirely over HTTP using JWT authentication.

---

## 1. Directory Structure

```
orchestration-service/
├── config.py             # Worker environment variables, DB URLs, Redis, and Auth credentials
├── database.py           # PostgreSQL Engine with Connection Pool (20 size, 10 overflow)
├── models.py             # SequenceExecution ORM model with task counter properties
├── orchestrator.py       # Core Orchestrator engine (TokenManager, DAG, Mappings, Saga Rollback, Retries)
├── worker.py             # ARQ Worker entrypoint (run_sequence_task, rollback_sequence_task)
├── run_worker.sh         # Worker startup shell script
├── samples/              # Ready-to-use JSON sequence recipe definitions
│   ├── 01_sequential_pipeline.json
│   ├── 02_parallel_steps.json
│   ├── 03_dynamic_field_mapping.json
│   ├── 04_conditional_branching.json
│   └── 05_retries_and_success_conditions.json
└── tests/
    └── test_worker.py    # Unit and mock tests for worker execution & Saga compensation
```

---

## 2. Worker Architecture & Execution Flow

```
Redis (ARQ Queue: "arq:queue")
          │
          │ (Worker consumes "run_sequence_task" job with `execution_id`)
          ▼
[worker.py -> run_sequence_task(ctx, execution_id)]
          │
          ▼
[orchestrator.py -> Orchestrator.run_sequence(execution_id, db_factory)]
          │
          ├─ 1. Fetches Execution from PostgreSQL (sets status="RUNNING")
          │
          ├─ 2. TokenManager: Authenticates against FastAPI /api/auth/login,
          │     caches JWT Bearer token in Redis with TTL.
          │
          ├─ 3. Iterates through Workflow Steps:
          │     ├── For Sequential step ("service_a"): Executes directly
          │     └── For Parallel step (["service_b", "service_c"]): Runs concurrently via `asyncio.gather`
          │
          ├─ 4. For Each Step:
          │     ├── Evaluates `skip_conditions` (if matched, sets status="SKIPPED")
          │     ├── Resolves dynamic field mappings from `trigger_payload` or previous steps
          │     ├── Dispatches POST to `http://localhost:8000/api/standalone/{service_name}`
          │     │   with `Authorization: Bearer <jwt>` and `X-Execution-Id`
          │     ├── Handles HTTP 429 Rate Limiting: Pauses for 60s (configurable) and retries
          │     ├── Evaluates custom `success_conditions` and HTTP status codes
          │     └── On Failure: Retries up to `max_retries` with exponential backoff & jitter
          │
          ├─ 5. Saga Compensation (on Critical Step Failure or Timeout):
          │     └── Dispatches reverse compensating POST requests to `/api/standalone/{name}/compensate`
          │
          └─ 6. Completion:
                ├── Updates Execution status to "COMPLETED", "PARTIAL_SUCCESS", or "FAILED"
                └── Dispatches `callback_url` webhook notification if configured.
```

---

## 3. Key Components

### A. Autonomous Token Manager (`TokenManager`)
- The worker does not require hardcoded long-lived secrets.
- On startup or token expiry, it authenticates with `ORCHESTRATOR_AUTH_USERNAME` and `ORCHESTRATOR_AUTH_PASSWORD` against FastAPI.
- It stores the token in Redis at key `los:orchestrator:jwt_token` with safety margin `(expires_in - 60s)` and injects `Authorization: Bearer <token>` in every outbound dispatch.

### B. Dynamic Field Transformations
The orchestrator supports declarative JSON mapping rules:
- `to_int`: Converts values to integers.
- `to_str`: Converts values to strings.
- `upper`: Converts string to uppercase.
- `lower`: Converts string to lowercase.
- Nested JSON dot-notation extraction (e.g. `data.user.id`).

### C. Rate Limit Handling (HTTP 429)
When a third-party service responds with HTTP 429, the orchestrator detects the status code, logs `[RATE_LIMITED_429]`, and pauses for `RATE_LIMIT_RETRY_DELAY_SECONDS` (default: 60s) before making its next attempt, avoiding immediate burnout of API quotas.

### D. Network Timeout Saga Rollback
If a mutating step times out (`httpx.TimeoutException`), the orchestrator tracks the step and invokes its `/compensate` endpoint during the rollback sequence to ensure orphan transactions in third-party systems are reconciled.
