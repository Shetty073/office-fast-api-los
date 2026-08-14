from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from utils import APIClient

class BaseService(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """The unique identifier for routing and field mappings."""
        pass

    @property
    def mock_enabled(self) -> bool:
        """Disabled by default in base class. Override to enable mocking."""
        return False

    @property
    def max_retries(self) -> int:
        """Default retry limit for sequence execution."""
        return 3

    @property
    def is_critical(self) -> bool:
        """If True, failure of this service fails the entire sequence. Otherwise continues as partial success."""
        return True

    def get_mock_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Implement to return service-specific mock data based on parameters."""
        raise NotImplementedError(f"Mock response not implemented for service: {self.name}")

    async def execute(
        self, 
        payload: Dict[str, Any], 
        execution_id: Optional[str] = None, 
        mock_override: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Standardized execution wrapper. Handles routing to mock behavior
        or executing actual logic, ensuring standard response formats.
        """
        # Determine if mocking is enabled: runtime payload override beats static settings
        should_mock = self.mock_enabled
        if mock_override is not None:
            should_mock = mock_override

        if should_mock:
            try:
                mock_data = self.get_mock_response(payload)
                return {
                    "success": True,
                    "data": mock_data,
                    "error": None,
                    "status_code": 200
                }
            except Exception as e:
                return {
                    "success": False,
                    "data": None,
                    "error": f"Mock error: {str(e)}",
                    "status_code": 500
                }

        # Real execution using DB-logging client
        client = APIClient(service_name=self.name, execution_id=execution_id)
        try:
            result = await self._run(payload, client)
            # Ensure compliance with standard response dictionary format
            if isinstance(result, dict) and "success" in result:
                return result
            
            return {
                "success": True,
                "data": result,
                "error": None,
                "status_code": 200
            }
        except Exception as e:
            return {
                "success": False,
                "data": None,
                "error": str(e),
                "status_code": 500
            }

    @abstractmethod
    async def _run(self, payload: Dict[str, Any], client: APIClient) -> Dict[str, Any]:
        """
        Developer API logic implementation.
        Must execute third-party requests via the provided client.
        """
        pass
