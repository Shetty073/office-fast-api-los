from typing import Dict, Type
from services.base import BaseService

class ServiceRegistry:
    _registry: Dict[str, BaseService] = {}

    @classmethod
    def register(cls, service_cls: Type[BaseService]) -> Type[BaseService]:
        """Instantiate and record a service class in the dynamic registry map."""
        instance = service_cls()
        name = instance.name
        if name in cls._registry:
            raise ValueError(f"Service '{name}' is already registered.")
        cls._registry[name] = instance
        return service_cls

    @classmethod
    def get(cls, name: str) -> BaseService:
        """Get a registered service instance by name."""
        if name not in cls._registry:
            raise KeyError(f"Service '{name}' is not registered.")
        return cls._registry[name]

    @classmethod
    def list_services(cls) -> list:
        """List the names of all registered services."""
        return list(cls._registry.keys())

def register_service(cls):
    """Decorator to dynamically register service classes."""
    return ServiceRegistry.register(cls)
