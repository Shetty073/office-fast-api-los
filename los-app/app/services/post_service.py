from typing import Dict, Any
from app.services.base import BaseService
from app.services.registry import register_service
from app.core.utils import APIClient

@register_service
class PostService(BaseService):
    @property
    def name(self) -> str:
        return "post_service"

    @property
    def is_critical(self) -> bool:
        return False

    def get_mock_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": 101,
            "title": payload.get("title", "Mock Post"),
            "body": payload.get("body", "Mock Post Body"),
            "userId": payload.get("userId", 1),
            "source": "mock"
        }

    async def _run(self, payload: Dict[str, Any], client: APIClient) -> Dict[str, Any]:
        response = client.post(
            "https://jsonplaceholder.typicode.com/posts",
            json=payload
        )

        if response.status_code == 201:
            return {
                "success": True,
                "data": response.json(),
                "error": None,
                "status_code": 201
            }

        return {
            "success": False,
            "data": None,
            "error": f"Failed to create post. Third-party status: {response.status_code}",
            "status_code": response.status_code
        }

    async def compensate(self, payload: Dict[str, Any], response: Dict[str, Any], client: APIClient) -> None:
        if response and isinstance(response, dict):
            created_data = response.get("data")
            if isinstance(created_data, dict):
                post_id = created_data.get("id")
                if post_id:
                    client.delete(f"https://jsonplaceholder.typicode.com/posts/{post_id}")
