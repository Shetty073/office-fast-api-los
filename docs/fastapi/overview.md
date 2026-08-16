# FastAPI Service (`los-app`) Developer Guide

Welcome to the **SCF LOS FastAPI Core Service** (`los-app`). This service acts as the central API gateway, service execution registry, security enforcement layer, and database persistence manager for loan origination workflows.

---

## 1. Directory Structure

```
los-app/
├── requirements.txt             # Core Python dependencies
├── run_app.sh                  # Shell startup script
├── app/
│   ├── main.py                 # FastAPI application entrypoint & Lifespan setup
│   ├── api/
│   │   ├── router.py           # Master router combining auth, standalone, sequences, chain
│   │   ├── deps.py             # Security dependencies (get_current_user, get_current_admin_user)
│   │   └── endpoints/
│   │       ├── auth.py         # App registration, login (JWT), user deactivation, profile
│   │       ├── standalone.py   # POST /api/standalone/{service_name} & compensation
│   │       ├── sequences.py    # Admin CRUD for sequence recipes (POST, GET, PUT, DELETE)
│   │       └── chain.py        # POST /api/chain/trigger, GET /status, POST /cancel, POST /retry
│   ├── core/
│   │   ├── config.py           # Settings, DB URLs, JWT secrets, pool sizes, idempotency windows
│   │   ├── logger.py           # Structured JSON contextual logger with RequestID & App tracking
│   │   ├── security.py         # Argon2/Bcrypt password hashing, AES-256-GCM encryption, JWT codec
│   │   ├── redis_pool.py       # Global async ARQ Redis connection pool
│   │   └── utils.py            # APIClient (HTTP dispatch & logging), Path resolver, Secret resolver
│   ├── db/
│   │   ├── base.py             # SQLAlchemy Declarative Base
│   │   └── session.py          # PostgreSQL Engine (Pool size 20, Max overflow 10, pre-ping), auto-migrator
│   ├── middleware/
│   │   ├── request_context.py  # Extracts X-Request-ID and JWT subject into ContextVars
│   │   ├── encryption.py       # Field-level/payload AES-GCM decryption and encryption
│   │   └── idempotency.py      # Hash-based SHA-256 deduplication with per-service window support
│   ├── models/
│   │   ├── base_mixin.py       # TimestampMixin (created_at, updated_at)
│   │   ├── user.py             # User & Client Application model
│   │   ├── sequence_definition.py # Registered workflow recipes
│   │   ├── sequence_execution.py  # Execution state, steps_data, status
│   │   └── api_log.py          # Third-party HTTP request & response audit trail
│   ├── schemas/
│   │   ├── auth.py             # Pydantic schemas for auth & registration
│   │   ├── mapping.py          # Cross-step field transformation schemas
│   │   ├── sequence_definition.py # Recipe creation and response schemas
│   │   └── sequence_execution.py  # Trigger request, status response, task counts
│   └── services/
│       ├── base.py             # BaseService abstract base class
│       ├── registry.py         # ServiceRegistry & @register_service decorator
│       ├── create_post_service.py # Real REST integration (POST /posts)
│       ├── get_post_service.py    # Real REST integration (GET /posts/{id})
│       └── update_post_service.py # Real REST integration (PUT /posts/{id})
└── tests/
    ├── conftest.py             # Pytest fixtures, mock Redis, in-memory DB, test clients
    ├── test_auth_and_middleware.py # Security, JWT, encryption, idempotency middleware tests
    ├── test_standalone_routes.py   # Standalone service execution tests
    ├── test_sequence_routes.py     # Recipe CRUD & admin privilege tests
    ├── test_chain_routes.py        # Sequence triggers, status, cancellation, retry tests
    ├── test_models.py              # ORM models and task count property tests
    ├── test_security.py            # Crypto & password hashing unit tests
    └── test_services.py            # Concrete service execution & compensation tests
```

---

## 2. Core Middlewares & Lifecycle Flow

Every incoming HTTP request traverses three layers of middleware in strict sequence:

```
Incoming Request
      │
      ▼
┌────────────────────────────────────────────────────────┐
│ 1. RequestContextMiddleware                            │
│    - Generates or extracts `X-Request-ID`              │
│    - Decodes JWT Bearer token (if present)             │
│    - Binds `request_id`, `client_app`, `username` into │
│      Python `contextvars` for structured logging       │
└─────────────────────────┬──────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────┐
│ 2. EncryptionMiddleware (Optional per User)            │
│    - If user has `enable_encryption=True`:             │
│      - Decrypts inbound `ciphertext` via AES-256-GCM   │
│      - Automatically encrypts outbound JSON response   │
└─────────────────────────┬──────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────┐
│ 3. HashIdempotencyMiddleware                           │
│    - For mutating requests (POST/PUT/PATCH/DELETE)     │
│    - Resolves `idempotency_window_ms` (per service)    │
│    - If window > 0: Computes SHA-256(Method+Path+Body) │
│      and acquires atomic lock in Redis                 │
│    - If duplicate within window: Returns HTTP 409      │
└─────────────────────────┬──────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────┐
│ 4. Route Handler & Security Dependency                 │
│    - `Depends(get_current_user)`: Mandatory Bearer JWT │
│    - `Depends(get_current_admin_user)`: Admin-only     │
└────────────────────────────────────────────────────────┘
```

---

## 3. Database Layer & Auto-Migration

- **Engine Configuration**:
  - `pool_size`: 20 connections
  - `max_overflow`: 10 connections
  - `pool_pre_ping=True`: Tests connection health before yielding from pool to prevent broken pipe errors.
- **Auto Migration (`auto_migrate_columns`)**:
  - Automatically runs on FastAPI startup (`main.py` lifespan).
  - Inspects existing PostgreSQL tables and dynamically issues `ALTER TABLE ... ADD COLUMN` for newly added model fields (e.g. `skip_conditions`, `success_conditions`, `trigger_payload`), preventing schema mismatch errors without requiring manual DDL scripts during development.

---

## 4. Standalone Service Invocation (`POST /api/standalone/{service_name}`)

When an external consumer or the ARQ Orchestrator triggers an API directly:
1. `ServiceRegistry.get(service_name)` resolves the service class instance.
2. The service executes its `_run(payload, client)` method.
3. Outbound calls made using `client.post(...)` or `client.get(...)` are automatically intercepted by `APIClient` and logged into the `api_logs` table with request body, response headers, HTTP status code, duration in milliseconds, and `execution_id`.

---

## 5. Security & RBI Compliance

1. **Authentication**: All endpoints (except `/api/auth/login`) require a signed HMAC-SHA256 JWT Bearer token.
2. **Access Control**: Sequence recipe creation and listing require `is_admin=True`.
3. **Data Integrity & Confidentiality**: AES-256-GCM encryption supported at the transport payload level for high-security environments.
4. **PII Masking**: The structured logger automatically masks sensitive fields (e.g., `password`, `pan`, `aadhaar`, `token`, `secret`) in log output.
