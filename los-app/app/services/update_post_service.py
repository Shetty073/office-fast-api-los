from typing import Dict, Any
from app.services.base import BaseService
from app.services.registry import register_service
from app.core.utils import APIClient

@register_service
class UpdatePostService(BaseService):
    @property
    def name(self) -> str:
        return "update_post_service"

    @property
    def is_critical(self) -> bool:
        return True

    def get_mock_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": payload.get("id") or payload.get("post_id", 1),
            "title": payload.get("title", "Updated Title"),
            "body": payload.get("body", "Updated Body"),
            "userId": payload.get("userId", 1),
            "source": "mock"
        }

    async def _run(self, payload: Dict[str, Any], client: APIClient) -> Dict[str, Any]:
        post_id = payload.get("id") or payload.get("post_id") or 1
        put_payload = {
            "id": post_id,
            "title": payload.get("title", "Updated Post Title"),
            "body": payload.get("body", "Updated Post Body"),
            "userId": payload.get("userId", 1)
        }

        # JSONPlaceholder supports PUT on /posts/{id} (1..100)
        target_id = post_id if isinstance(post_id, int) and post_id <= 100 else 1
        response = client.put(
            f"https://jsonplaceholder.typicode.com/posts/{target_id}",
            json=put_payload
        )

        if response.status_code == 200:
            data = response.json()
            if post_id != target_id:
                data["id"] = post_id
            return {
                "success": True,
                "data": data,
                "error": None,
                "status_code": 200
            }

        return {
            "success": False,
            "data": None,
            "error": f"Failed to update post. Third-party status: {response.status_code}",
            "status_code": response.status_code
        }

    async def compensate(self, payload: Dict[str, Any], response: Dict[str, Any], client: APIClient) -> None:
        # Revert / compensation logic if needed
        pass
