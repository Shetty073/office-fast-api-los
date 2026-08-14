# Success Conditions

Success conditions define assertions that a service's response must meet to be considered successful during orchestrations (or standalone runs). If a service fails any success condition, its step execution status transitions to `FAILED`.

---

## Configuration Types

Success conditions can be defined:
1. **Statically (Service Class Defaults)**: Default rules declared in Python within the service's class definition.
2. **Dynamically (Trigger Payloads)**: Runtime overrides specified directly in the `POST /api/chain/trigger` payload.

---

## Condition Schema

A success condition configuration consists of two optional validation keys:

```json
{
  "status_codes": [200, 201],
  "body_rules": {
    "data.key_name": "expected_value",
    "status_code": 200
  }
}
```

### Validation Keys
1. **`status_codes`** (List of Integers):
   * A list of acceptable HTTP status codes returned by the service wrapper or downstream API.
   * *Example:* `[200]` or `[200, 201]`.
2. **`body_rules`** (Dictionary of String -> Any):
   * Dot-notated paths mapped to expected values. Paths are evaluated against the entire standardized service execution response.
   * To check keys in the nested payload returned by the third-party API, prefix the path with `data.`.
   * *Example:* `{"data.completed": true}` asserts that the nested key `completed` inside the response data is `true`.

---

## Statically Defining Defaults (in Code)

To define a default success condition for a service, override the `success_conditions` property in the service class:

```python
from typing import Dict, Any
from services.base import BaseService

class MyCustomService(BaseService):
    # ...
    
    @property
    def success_conditions(self) -> Dict[str, Any]:
        return {
            "status_codes": [200],
            "body_rules": {
                "data.completed": True
            }
        }
```

---

## Dynamically Overriding Conditions (in Request Payload)

You can pass custom success conditions at runtime when triggering a sequence. These will override any defaults defined in the service classes.

### Request Payload Example:
```json
{
    "sequence": ["todo_service"],
    "inputs": {
        "todo_service": {"todo_id": 1}
    },
    "success_conditions": {
        "todo_service": {
            "status_codes": [200],
            "body_rules": {
                "data.completed": false
            }
        }
    }
}
```
In this scenario, if the `todo_service` returns a response with `"completed": true`, the orchestrator fails the step with an validation error:
`Success condition failed: key 'data.completed' expected False, got True`.
