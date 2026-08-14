# Migration Guide: Porting Orchestration Features

This guide explains how to migrate the dynamic API orchestration and logging components from this project into an existing FastAPI project.

---

## 1. Components to Lift

Port the following files from this repository directly into the target project structure:

| File / Folder | Role | Destination |
| :--- | :--- | :--- |
| **[`utils.py`](file:///Users/ashishshetty/Projects/office-fast-api-los/utils.py)** | Contains `APIClient` (persisting logs) and path helpers (`get_by_path`, `set_by_path`). | `app/utils/` or project helpers folder. |
| **[`orchestrator.py`](file:///Users/ashishshetty/Projects/office-fast-api-los/orchestrator.py)** | Coordinates sequence execution, data mapping, retries, and statuses. | `app/orchestrator/` or main app layer. |
| **[`services/`](file:///Users/ashishshetty/Projects/office-fast-api-los/services/)** (entire directory) | Contains the base service class, registry, decorators, and integration scripts. | `app/services/` |

---

## 2. Integration Steps in Target Project

### Step A: Merge Database Models
Add the database tables to your target project's ORM layer.
1. Copy the `SequenceExecution` and `APILog` classes from [`models.py`](file:///Users/ashishshetty/Projects/office-fast-api-los/models.py) into your target project's models module (e.g., `app/models.py`).
2. Generate and run a database migration (e.g., using Alembic) to create the `sequence_executions` and `api_logs` tables in the production DB:
   ```bash
   alembic revision --autogenerate -m "Add orchestration and api logs tables"
   alembic upgrade head
   ```

### Step B: Import Path Adjustments
Since you are relocating these files, update absolute package imports.
* *Example:* If you place files under `app/`, update imports in [`orchestrator.py`](file:///Users/ashishshetty/Projects/office-fast-api-los/orchestrator.py) and [`services/base.py`](file:///Users/ashishshetty/Projects/office-fast-api-los/services/base.py):
  ```python
  # Change:
  from database import get_db
  # To:
  from app.database import get_db
  ```

### Step C: Register routes in Target FastAPI Init
Mount the orchestrator APIRouter onto your main FastAPI application.
In your target project's startup module (e.g., `app/main.py`):
```python
from fastapi import FastAPI
from app.routes import router as orchestration_router  # Router copied from routes.py

app = FastAPI()

app.include_router(orchestration_router)
```

### Step D: Merge Requirements
Ensure dependencies from [`requirements.txt`](file:///Users/ashishshetty/Projects/office-fast-api-los/requirements.txt) are added to your target project (`pyproject.toml`, `Pipfile`, or `requirements.txt`):
* `sqlalchemy>=2.0.0`
* `cryptography>=42.0.0`
* `pymysql>=1.1.0` (if migrating to MySQL/MariaDB)

---

## 3. Critical Considerations for a Successful Migration

### ⚠️ Thread Safety & Db Session Lifecycles in Background Tasks
In FastAPI, passing a request-scoped database Session (yielded from `Depends(get_db)`) directly into a background task worker is dangerous because the request terminates and closes the connection before the worker finishes executing.

**How we solved this (and you must maintain it):**
When handoff occurs in `routes.py`, we pass the database session generator/factory callable (`get_db`) rather than the active session object itself:
```python
# routes.py
background_tasks.add_task(Orchestrator.run_sequence, execution.id, get_db)
```
Inside [`orchestrator.py`](file:///Users/ashishshetty/Projects/office-fast-api-los/orchestrator.py), the background thread instantiates and manages the session lifecycle internally:
```python
db_gen = get_db_session()
db = next(db_gen)
try:
    # ... execute steps ...
finally:
    next(db_gen) # safely closes connection
```
Ensure your target database generator follows a matching pattern.

### ⚠️ Service Autoregistration Lifecycle
The registry decorator `@register_service` requires Python to load the module into memory to execute the decoration logic.
* Ensure all custom service modules are explicitly imported in `app/services/__init__.py`.
* Ensure `import app.services` is executed early during startup (e.g. in your main file) to guarantee all decorators run before any endpoint calls or orchestrations occur.

### ⚠️ DB Logger Connection Configuration
The `APIClient` utility wraps Python's standard `requests` library and uses the `SessionLocal` factory inside `utils.py` to write logs to `api_logs`.
* If your target project uses a different session maker naming convention (e.g., `db_session` instead of `SessionLocal`), update [`utils.py`](file:///Users/ashishshetty/Projects/office-fast-api-los/utils.py) accordingly.
