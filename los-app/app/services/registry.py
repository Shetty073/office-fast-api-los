from typing import Dict, Type, List
import logging
from app.services.base import BaseService

logger = logging.getLogger(__name__)

class ServiceRegistry:
    _registry: Dict[str, BaseService] = {}

    @classmethod
    def register(cls, service_cls: Type[BaseService]) -> Type[BaseService]:
        """Class decorator to register a service dynamically."""
        instance = service_cls()
        cls._registry[instance.name] = instance
        logger.info(f"Registered service: {instance.name}")
        return service_cls

    @classmethod
    def get(cls, name: str) -> BaseService:
        """Fetch an instantiated service by its registered name."""
        if name not in cls._registry:
            raise KeyError(f"Service '{name}' is not registered in the system.")
        return cls._registry[name]

    @classmethod
    def list_services(cls) -> List[str]:
        """List all available service names."""
        return list(cls._registry.keys())

def register_service(cls: Type[BaseService]) -> Type[BaseService]:
    """Convenience decorator function for registering services."""
    return ServiceRegistry.register(cls)
