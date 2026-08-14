from typing import Dict, Any
from services.base import BaseService
from services.registry import register_service
from utils import APIClient

@register_service
class PostService(BaseService):
    @property
    def name(self) -> str:
        return "post_service"

    @property
    def mock_enabled(self) -> bool:
        # Enabled by default for demonstration
        return True

    def get_mock_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Provides mock post data using request parameters."""
        title = payload.get("title", "Mock Post Title")
        body = payload.get("body", "Mock Post Body")
        user_id = payload.get("userId", 1)
        return {
            "id": 101,
            "title": title,
            "body": body,
            "userId": user_id,
            "source": "mock"
        }

    async def _run(self, payload: Dict[str, Any], client: APIClient) -> Dict[str, Any]:
        """Creates a post on jsonplaceholder. Mapping is handled here inside the service."""
        api_payload = {
            "title": payload.get("title"),
            "body": payload.get("body"),
            "userId": payload.get("userId")
        }

        if not api_payload["title"] or not api_payload["userId"]:
            return {
                "success": False,
                "data": None,
                "error": "title and userId are required parameters",
                "status_code": 400
            }

        response = client.post(
            "https://jsonplaceholder.typicode.com/posts",
            json=api_payload,
            headers={"Content-Type": "application/json"}
        )

        if response.status_code in [200, 201]:
            return {
                "success": True,
                "data": response.json(),
                "error": None,
                "status_code": response.status_code
            }

        return {
            "success": False,
            "data": None,
            "error": f"Failed to create post. Third-party status: {response.status_code}",
            "status_code": response.status_code
        }

    async def compensate(self, payload: Dict[str, Any], response: Dict[str, Any], client: APIClient) -> None:
        """Simulate Saga compensating rollback transaction by deleting the created post."""
        post_id = 101
        if response and isinstance(response, dict) and "data" in response and isinstance(response["data"], dict):
            post_id = response["data"].get("id", post_id)
        client.delete(f"https://jsonplaceholder.typicode.com/posts/{post_id}")
