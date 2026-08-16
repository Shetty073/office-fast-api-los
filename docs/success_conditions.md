# Success Conditions & Assertion Rules

Success conditions define assertions that a service's response must meet to be considered successful during orchestrations (or standalone runs). If a service fails any success condition, its step execution status transitions to `FAILED`, and the orchestrator triggers the **Saga pattern rollback**.

---

## 1. Configuration Schema

Success conditions can be defined statically on the `BaseService` or dynamically in sequence recipes / trigger payloads:

```json
{
  "status_codes": [200, 201],
  "body_rules": {
    "data.status": "ACTIVE",
    "data.verified": true,
    "success": true
  }
}
```

### Validation Keys
1. **`status_codes`** (List of Integers):
   - Acceptable HTTP status codes returned by the service wrapper or downstream API.
   - *Example:* `[200]` or `[200, 201]`.
2. **`body_rules`** (Dictionary of String -> Any):
   - Dot-notated paths mapped to expected values.
   - *Example:* `{"data.completed": true}` asserts that the nested key `completed` inside `data` is `true`.

---

## 2. Setting Default Success Conditions in Python

In your service class in `los-app/app/services/my_service.py`:

```python
from typing import Dict, Any
from app.services.base import BaseService
from app.services.registry import register_service

@register_service
class MyService(BaseService):
    @property
    def name(self) -> str:
        return "my_service"

    @property
    def success_conditions(self) -> Dict[str, Any]:
        return {
            "status_codes": [200],
            "body_rules": {
                "data.status": "ACTIVE"
            }
        }
```

---

## 3. Configuring Success Conditions in JSON Recipes

In a database sequence definition (`POST /api/sequences`):

```json
{
  "name": "resilient_verification_pipeline",
  "sequence": ["todo_service", "post_service"],
  "success_conditions": {
    "todo_service": {
      "status_codes": [200],
      "body_rules": {
        "data.completed": true
      }
    }
  }
}
```
If `todo_service` returns `"completed": false`, the step fails, retries if configured, and if still unsuccessful triggers the Saga rollback compensating previously executed steps.
