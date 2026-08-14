from services.base import BaseService
from services.registry import ServiceRegistry, register_service

# Import service modules to trigger decorator-based registration
import services.todo_service
import services.post_service
