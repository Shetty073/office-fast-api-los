import uuid
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.logger import request_id_ctx, client_app_ctx, username_ctx
from app.core.security import decode_access_token

class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Extracts or creates X-Request-ID and parses JWT token (if present)
    to set asynchronous logger context variables.
    """
    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = req_id
        request_id_ctx.set(req_id)

        # Inspect authorization header for context injection
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = decode_access_token(token)
            if payload:
                client_app_ctx.set(payload.get("app_name", "client_app"))
                username_ctx.set(payload.get("sub", "user"))
            else:
                client_app_ctx.set("unauthenticated")
                username_ctx.set("anonymous")
        else:
            client_app_ctx.set("public")
            username_ctx.set("anonymous")

        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response
