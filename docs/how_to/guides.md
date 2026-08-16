# How-To Guides (Junior Developer Walkthrough)

This directory contains practical, copy-pasteable step-by-step guides for adding new services, creating sequence recipes, and running executions.

---

## Guide 1: How to Add a New Standalone Service

Adding an integration requires zero changes to the core orchestrator or routing layer.

### Step 1: Create the Service Class
Create a new file in `los-app/app/services/my_kyc_service.py`:

```python
from typing import Dict, Any
from app.services.base import BaseService
from app.services.registry import register_service
from app.core.utils import APIClient

@register_service
class MyKYCService(BaseService):
    @property
    def name(self) -> str:
        # Unique identifier used in URLs and JSON sequence definitions
        return "my_kyc_service"

    @property
    def is_critical(self) -> bool:
        # If True, failure in a workflow triggers Saga rollback
        return True

    @property
    def timeout(self) -> float:
        # HTTP timeout in seconds
        return 15.0

    @property
    def idempotency_window_ms(self) -> int:
        # Custom deduplication window in ms. Set to 0 to disable.
        return 5000

    def get_mock_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Return mock payload for testing / offline development (?mock=true)
        return {
            "pan": payload.get("pan", "ABCDE1234F"),
            "kyc_status": "VERIFIED",
            "score": 850,
            "source": "mock"
        }

    async def _run(self, payload: Dict[str, Any], client: APIClient) -> Dict[str, Any]:
        # Outbound HTTP call using APIClient (auto-logged to api_logs table)
        response = client.post(
            "https://api.partner-kyc.com/v1/verify",
            json={"pan_number": payload.get("pan")}
        )

        if response.status_code == 200:
            return {
                "success": True,
                "data": response.json(),
                "status_code": 200
            }

        return {
            "success": False,
            "error": f"KYC verification failed: {response.text}",
            "status_code": response.status_code
        }

    async def compensate(self, payload: Dict[str, Any], response: Dict[str, Any], client: APIClient) -> None:
        # Optional: Saga rollback compensation logic
        pass
```

### Step 2: Export in `los-app/app/services/__init__.py`
Open `los-app/app/services/__init__.py` and add:
```python
from app.services.my_kyc_service import MyKYCService
```

### Step 3: Test Standalone
```bash
curl -X POST http://localhost:8000/api/standalone/my_kyc_service?mock=true \
  -H "Authorization: Bearer <your_token>" \
  -H "Content-Type: application/json" \
  -d '{"pan": "ABCDE1234F"}'
```

---

## Guide 2: How to Create and Register a New Sequence Recipe

### Step 1: Define the Workflow in JSON
Suppose we want to execute:
1. `create_post_service`
2. `get_post_service` (using `data.id` from step 1)
3. `update_post_service` (skip if `context.skip_update == True`)

### Step 2: Register via API (Admin Token Required)
```http
POST /api/sequences
Authorization: Bearer {{admin_token}}
Content-Type: application/json

{
    "name": "loan_onboarding_pipeline",
    "description": "Onboards loan application: KYC verification and credit evaluation",
    "sequence": [
        "create_post_service",
        "get_post_service",
        "update_post_service"
    ],
    "default_inputs": {
        "create_post_service": { "userId": 1 },
        "get_post_service": {},
        "update_post_service": { "userId": 1 }
    },
    "mappings": [
        {
            "from_service": "trigger_payload",
            "from_field": "title",
            "to_service": "create_post_service",
            "to_field": "title"
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
            "from_field": "updated_title",
            "to_service": "update_post_service",
            "to_field": "title"
        }
    ],
    "skip_conditions": [
        {
            "service": "update_post_service",
            "condition": "context.skip_update == True",
            "reason": "Skipped update because context flag was True"
        }
    ]
}
```

---

## Guide 3: How to Trigger a Sequence and Query its Status

### Step 1: Trigger the Workflow
```http
POST /api/chain/trigger/loan_onboarding_pipeline
Authorization: Bearer {{token}}
Content-Type: application/json

{
    "payload": {
        "title": "Loan App 101",
        "updated_title": "Loan App 101 Approved"
    }
}
```
**Response**:
```json
{
    "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "task_name": "loan_onboarding_pipeline"
}
```

### Step 2: Check Real-Time Execution Status
```http
GET /api/chain/status/a1b2c3d4-e5f6-7890-abcd-ef1234567890
Authorization: Bearer {{token}}
```
**Response**:
```json
{
    "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": "COMPLETED",
    "count": {
        "total": 3,
        "completed": 3,
        "failed": 0,
        "pending": 0
    },
    "data": {
        "create_post_service": {
            "success": true,
            "data": { "id": 101, "title": "Loan App 101" },
            "status_code": 201
        },
        "get_post_service": {
            "success": true,
            "data": { "id": 101, "title": "Loan App 101" },
            "status_code": 200
        },
        "update_post_service": {
            "success": true,
            "data": { "id": 101, "title": "Loan App 101 Approved" },
            "status_code": 200
        }
    }
}
```

---

## Guide 4: How to Resume a Failed Sequence from Point of Failure

If a sequence encounters a failure (e.g. downstream service outage), you can resume it without restarting completed steps:

```http
POST /api/chain/trigger/loan_onboarding_pipeline
Authorization: Bearer {{token}}
Content-Type: application/json

{
    "previous_task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

The orchestrator will:
1. Load previous successful outputs.
2. Mark failed and subsequent steps as `PENDING`.
3. Re-execute beginning exactly from the first failed step.
