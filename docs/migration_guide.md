# Migration & Separation Guide: Running FastAPI & ARQ Independently

This repository is split cleanly into two independent microservices that share zero libraries or code:
1. **`los-app/`**: Standalone FastAPI REST API engine.
2. **`orchestration-service/`**: Generic, database-driven ARQ worker executing asynchronous workflows.

---

## 1. Directory Structure

```
├── los-app/                               # FastAPI Application
│   ├── requirements.txt                   # Independent requirements
│   ├── run_app.sh                         # Production-ready Uvicorn starter
│   ├── app/
│   │   ├── main.py                        # FastAPI entrypoint
│   │   ├── api/router.py                  # API router
│   │   ├── api/endpoints/                 # standalone.py, sequences.py, chain.py
│   │   ├── core/                          # config.py, redis_pool.py, utils.py
│   │   ├── db/                            # base.py, session.py
│   │   ├── models/                        # SQLAlchemy models
│   │   ├── schemas/                       # Pydantic schemas
│   │   └── services/                      # BaseService, registry, sequence_manager, integrations
│   └── tests/
│
└── orchestration-service/                 # Standalone ARQ Worker
    ├── requirements.txt                   # Independent requirements
    ├── run_worker.sh                      # Production-ready ARQ worker starter
    ├── config.py                          # Worker configuration
    ├── database.py                        # Independent database session
    ├── models.py                          # Independent database models
    ├── orchestrator.py                    # Generic HTTP orchestrator
    ├── worker.py                          # ARQ worker functions & settings
    ├── samples/                           # Sample JSON workflow definitions
    └── tests/
```

---

## 2. Running in Production

### Step 1: Start PostgreSQL & Redis
Ensure PostgreSQL and Redis are running:
- PostgreSQL: `localhost:5432` with database `office_proj` (or configured via `DATABASE_URL`).
- Redis: `localhost:6379` (or configured via `REDIS_HOST`/`REDIS_PORT`).

### Step 2: Start the FastAPI Engine (`los-app/`)
```bash
cd los-app
pip install -r requirements.txt
./run_app.sh
```
Or with custom production parameters:
```bash
HOST=0.0.0.0 PORT=8000 WORKERS=4 LOG_LEVEL=info ./run_app.sh
```

### Step 3: Start the Standalone ARQ Worker (`orchestration-service/`)
In a separate process / container:
```bash
cd orchestration-service
pip install -r requirements.txt
./run_worker.sh
```
Or with custom production parameters:
```bash
MAX_JOBS=50 POLL_DELAY=0.2 FASTAPI_BASE_URL=http://localhost:8000 ./run_worker.sh
```

---

## 3. How the Orchestrator Interacts with FastAPI
1. FastAPI stores workflow recipes in PostgreSQL (`sequence_definitions`).
2. When triggered via `POST /api/chain/trigger/{name}`, FastAPI enqueues the job ID into Redis.
3. The ARQ worker pulls the job and calls FastAPI standalone endpoints (`POST /api/standalone/{service_name}`) via HTTP.
4. The worker automatically sets:
   - `X-Execution-Source: orchestrator`
   - `X-Execution-Id: <execution_uuid>`
5. Zero service-specific code exists in `orchestration-service/`. Any new API added to `los-app/app/services/` is immediately orchestratable!
