from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from utils import APIClient, get_by_path

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

    @property
    def timeout(self) -> float:
        """Default request timeout for the service integration."""
        return 10.0

    async def compensate(self, payload: Dict[str, Any], response: Dict[str, Any], client: APIClient) -> None:
        """
        Compensating transaction logic (Saga Rollback) for this service.
        Override in subclasses to delete created resources, cancel applications, etc.
        """
        pass

    @property
    def success_conditions(self) -> Optional[Dict[str, Any]]:
        """
        Statically defined default success conditions for the service.
        Can specify allowed 'status_codes' and 'body_rules'.
        """
        return None

    def get_mock_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Implement to return service-specific mock data based on parameters."""
        raise NotImplementedError(f"Mock response not implemented for service: {self.name}")

    async def execute(
        self, 
        payload: Dict[str, Any], 
        execution_id: Optional[str] = None, 
        mock_override: Optional[bool] = None,
        success_conditions: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Standardized execution wrapper. Handles routing to mock behavior
        or executing actual logic, ensuring standard response formats,
        and validating against success conditions.
        """
        # Determine if mocking is enabled: runtime payload override beats static settings
        should_mock = self.mock_enabled
        if mock_override is not None:
            should_mock = mock_override

        if should_mock:
            try:
                mock_data = self.get_mock_response(payload)
                result = {
                    "success": True,
                    "data": mock_data,
                    "error": None,
                    "status_code": 200
                }
            except Exception as e:
                result = {
                    "success": False,
                    "data": None,
                    "error": f"Mock error: {str(e)}",
                    "status_code": 500
                }
        else:
            # Real execution using DB-logging client
            client = APIClient(service_name=self.name, execution_id=execution_id, timeout=self.timeout)
            try:
                result = await self._run(payload, client)
                # Ensure compliance with standard response dictionary format
                if not isinstance(result, dict) or "success" not in result:
                    result = {
                        "success": True,
                        "data": result,
                        "error": None,
                        "status_code": 200
                    }
            except Exception as e:
                result = {
                    "success": False,
                    "data": None,
                    "error": str(e),
                    "status_code": 500
                }

        # Apply success conditions checks
        conditions = success_conditions if success_conditions is not None else self.success_conditions
        if conditions and result.get("success"):
            # Check status codes
            allowed_codes = conditions.get("status_codes")
            if allowed_codes is not None:
                actual_code = result.get("status_code")
                if actual_code not in allowed_codes:
                    result["success"] = False
                    result["error"] = f"Success condition failed: status code {actual_code} not in {allowed_codes}"
            
            # Check body rules
            body_rules = conditions.get("body_rules")
            if body_rules and result.get("success"):
                for path, expected_val in body_rules.items():
                    actual_val = get_by_path(result, path)
                    if actual_val != expected_val:
                        result["success"] = False
                        result["error"] = f"Success condition failed: key '{path}' expected {expected_val}, got {actual_val}"
                        break

        return result

    @abstractmethod
    async def _run(self, payload: Dict[str, Any], client: APIClient) -> Dict[str, Any]:
        """
        Developer API logic implementation.
        Must execute third-party requests via the provided client.
        """
        pass
