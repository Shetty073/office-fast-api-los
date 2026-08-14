from typing import Dict, Any
from services.base import BaseService
from services.registry import register_service
from utils import APIClient

@register_service
class TodoService(BaseService):
    @property
    def name(self) -> str:
        return "todo_service"

    @property
    def success_conditions(self) -> Dict[str, Any]:
        return {
            "status_codes": [200]
        }

    # mock_enabled is False by default

    def get_mock_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Provides mock todo data."""
        todo_id = payload.get("todo_id", 1)
        return {
            "userId": 99,
            "id": todo_id,
            "title": f"Mocked Todo Title {todo_id}",
            "completed": True,
            "source": "mock"
        }

    async def _run(self, payload: Dict[str, Any], client: APIClient) -> Dict[str, Any]:
        """Runs the actual HTTP request using the DB-logging client."""
        todo_id = payload.get("todo_id")
        if not todo_id:
            return {
                "success": False,
                "data": None,
                "error": "todo_id parameter is required",
                "status_code": 400
            }

        response = client.get(f"https://jsonplaceholder.typicode.com/todos/{todo_id}")
        
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
            "error": f"Failed to fetch todo. Third-party status: {response.status_code}",
            "status_code": response.status_code
        }
