# Adding a New API / Service Guide (Junior Dev Cheat-Sheet)

Welcome to the **SCF LOS Engine**! This project is organized so that adding a new third-party integration or internal API is straightforward and requires zero modifications to the core orchestrator.

---

## 1. Project Layout (`los-app/`)

```
los-app/
├── requirements.txt
├── app/
│   ├── main.py                  # FastAPI entry point & lifespan
│   ├── api/
│   │   ├── router.py            # Aggregated API router (/api/...)
│   │   └── endpoints/
│   │       ├── standalone.py    # POST /api/standalone/{service_name}
│   │       ├── sequences.py     # POST/GET /api/sequences
│   │       └── chain.py         # POST /api/chain/trigger, /status, /cancel, /retry
│   ├── core/
│   │   ├── config.py            # Environment variables & DB settings
│   │   ├── redis_pool.py        # Redis connection pool for ARQ
│   │   └── utils.py             # Path helpers, SecretResolver, and APIClient
│   ├── db/
│   │   ├── base.py              # SQLAlchemy Base model
│   │   └── session.py           # DB engine, session maker, get_db()
│   ├── models/
│   │   ├── sequence_definition.py
│   │   ├── sequence_execution.py
│   │   └── api_log.py
│   ├── schemas/
│   │   ├── mapping.py
│   │   ├── sequence_definition.py
│   │   └── sequence_execution.py
│   └── services/
│       ├── base.py              # BaseService abstract class
│       ├── registry.py          # ServiceRegistry & @register_service decorator
│       ├── todo_service.py      # Example integration
│       └── post_service.py      # Example integration
└── tests/
    ├── conftest.py
    ├── test_models.py
    ├── test_routes.py
    └── test_services.py
```

---

## 2. Step-by-Step: Adding a New Service

### Step 1: Create your Service File
Create a new file in `los-app/app/services/my_service.py`:

```python
from typing import Dict, Any
from app.services.base import BaseService
from app.services.registry import register_service
from app.core.utils import APIClient

@register_service
class MyService(BaseService):
    @property
    def name(self) -> str:
        # Unique identifier used in API URLs and JSON sequence definitions
        return "my_service"

    @property
    def is_critical(self) -> bool:
        # If True, failure in a sequence halts the workflow and triggers Saga rollback
        return True

    def get_mock_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Return mock payload for testing and local development (?mock=true)
        return {
            "customer_id": payload.get("customer_id", 123),
            "status": "APPROVED",
            "source": "mock"
        }

    async def _run(self, payload: Dict[str, Any], client: APIClient) -> Dict[str, Any]:
        # Perform HTTP call using APIClient (all calls are auto-logged to api_logs table)
        response = client.post(
            "https://api.thirdparty.com/v1/verify",
            json=payload
        )
        if response.status_code == 200:
            return {
                "success": True,
                "data": response.json(),
                "status_code": 200
            }
        return {
            "success": False,
            "error": f"Error response: {response.text}",
            "status_code": response.status_code
        }

    async def compensate(self, payload: Dict[str, Any], response: Dict[str, Any], client: APIClient) -> None:
        # Optional: Undo this action if a later step fails (Saga Rollback)
        pass
```

### Step 2: Export in `los-app/app/services/__init__.py`
Add your service to `los-app/app/services/__init__.py`:
```python
from app.services.my_service import MyService
```

### Step 3: Test Standalone API Call
Run your app and call:
```bash
POST http://localhost:8000/api/standalone/my_service?mock=true
Body: { "customer_id": 123 }
```

### Step 4: Include in Sequence Workflows
Register your new service in a sequence recipe (`POST /api/sequences`) or trigger it via the ARQ orchestrator. No changes to the `orchestration-service` are needed!
