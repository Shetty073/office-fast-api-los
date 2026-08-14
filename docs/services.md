# Implementing New Services

This developer guide walks through creating and registering a new service in the SCF LOS engine.

---

## Step-by-Step Implementation

To implement a new service:
1. **Create the file**: Add a new Python module in the `services/` directory (e.g. `services/my_new_service.py`).
2. **Inherit from `BaseService`**: Extend the base class defined in `services/base.py`.
3. **Register the Service**: Use the `@register_service` decorator to dynamically register the service in the engine.
4. **Implement required methods**:
   * `name` (property): Return a unique service identifier.
   * `get_mock_response`: Define the JSON mock response.
   * `_run`: Define the actual API execution logic.
5. **Import in package init**: Add your module to `services/__init__.py` so that decorators run at application startup.

---

## Code Template

Here is a boilerplate template for a new service:

```python
from typing import Dict, Any
from services.base import BaseService
from services.registry import register_service
from utils import APIClient

@register_service
class MyNewService(BaseService):
    @property
    def name(self) -> str:
        """The routing key name for this service."""
        return "my_new_service"

    @property
    def mock_enabled(self) -> bool:
        """Override to True if you want mock response to be active by default."""
        return False

    @property
    def success_conditions(self) -> Dict[str, Any]:
        """Define default success conditions (optional)."""
        return {
            "status_codes": [200, 201]
        }

    def get_mock_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Define mock response data."""
        return {
            "status": "mocked",
            "received_input": payload.get("some_input", "default")
        }

    async def _run(self, payload: Dict[str, Any], client: APIClient) -> Dict[str, Any]:
        """
        The main HTTP integration. Always use `client` to issue requests
        so that every detail is automatically logged to the `api_logs` table.
        """
        user_input = payload.get("some_input")
        if not user_input:
            return {
                "success": False,
                "data": None,
                "error": "some_input parameter is required",
                "status_code": 400
            }

        # Issue third-party HTTP call using the DB-logging client wrapper
        response = client.post(
            "https://api.example.com/endpoint",
            json={"input": user_input},
            headers={"Authorization": "Bearer token"}
        )

        if response.status_code == 200:
            return {
                "success": True,
                "data": response.json(),
                "error": None,
                "status_code": 200
            }

        return {
            "success": False,
            "data": None,
            "error": f"API error. Downstream status: {response.status_code}",
            "status_code": response.status_code
        }
```

---

## Activating the Service

For the dynamic decorator registration to work, you must import the service file inside the `services/__init__.py` module. 

Open [`services/__init__.py`](file:///Users/ashishshetty/Projects/office-fast-api-los/services/__init__.py) and add:

```python
from . import my_new_service
```
Once added, your service is ready to run standalone or within orchestrations under the identifier `"my_new_service"`.
