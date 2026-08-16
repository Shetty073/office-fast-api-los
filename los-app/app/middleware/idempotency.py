import hashlib
import json
import logging
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from app.core import config
from app.core.redis_pool import get_arq_redis
from app.core.logger import client_app_ctx

logger = logging.getLogger(__name__)

class HashIdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Hash-based request deduplication middleware with configurable millisecond window.
    Computes SHA-256(method + path + client_app + raw_body).
    If an identical request is received within IDEMPOTENCY_WINDOW_MS from the same client,
    returns 409 Conflict to protect against duplicate downstream transactions.
    """
    def __init__(self, app, window_ms: int = config.IDEMPOTENCY_WINDOW_MS):
        super().__init__(app)
        self.window_ms = window_ms

    async def dispatch(self, request: Request, call_next):
        # Apply deduplication only on mutating HTTP methods
        if request.method not in ["POST", "PUT", "PATCH", "DELETE"]:
            return await call_next(request)

        # Skip idempotency check on auth login endpoints
        if request.url.path.startswith("/api/auth/login"):
            return await call_next(request)

        # Determine effective idempotency window
        effective_window_ms = self.window_ms

        # Check if this is a standalone service endpoint (/api/standalone/{service_name})
        path_parts = request.url.path.strip("/").split("/")
        if len(path_parts) >= 3 and path_parts[0] == "api" and path_parts[1] == "standalone":
            service_name = path_parts[2]
            try:
                from app.services.registry import ServiceRegistry
                service = ServiceRegistry.get(service_name)
                effective_window_ms = service.idempotency_window_ms
            except Exception:
                effective_window_ms = self.window_ms

        # If idempotency is disabled for this service (window_ms <= 0), bypass checking
        if effective_window_ms <= 0:
            return await call_next(request)

        body_bytes = await request.body()
        app_name = client_app_ctx.get()
        
        # Build deterministic fingerprint
        fingerprint_source = f"{request.method}:{request.url.path}:{app_name}:{body_bytes.decode('utf-8', errors='ignore')}"
        req_hash = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
        redis_key = f"idempotency:hash:{req_hash}"

        try:
            redis = await get_arq_redis()
            # Set key with millisecond expiration (px=effective_window_ms), only if key does not exist (nx=True)
            acquired = await redis.set(redis_key, "PROCESSING", px=effective_window_ms, nx=True)
            
            if not acquired:
                logger.warning(f"Duplicate request detected within {effective_window_ms}ms window (Hash: {req_hash[:12]})")
                return JSONResponse(
                    status_code=409,
                    content={
                        "detail": f"Duplicate request rejected. A matching request was submitted within the {effective_window_ms}ms idempotency window.",
                        "error_code": "DUPLICATE_REQUEST_BLOCKED",
                        "idempotency_hash": req_hash,
                        "window_ms": effective_window_ms
                    }
                )
        except Exception as e:
            # If Redis connection is down, log and continue to avoid blocking traffic
            logger.debug(f"Idempotency Redis check bypassed: {e}")

        # Re-set body for downstream ASGI consumers
        async def receive():
            return {"type": "http.request", "body": body_bytes}
        request._receive = receive

        response: Response = await call_next(request)
        return response
