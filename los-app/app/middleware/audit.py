import time
import json
import logging
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse
from app.db.session import SessionLocal
from app.models.audit_log import AuditLog
from app.core.logger import mask_pii_string, mask_pii_data, request_id_ctx, client_app_ctx, username_ctx

logger = logging.getLogger("audit")

class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """
    Comprehensive Audit Logging Middleware.
    Logs request/response pairs against request_id with full PII masking (DPDP compliant)
    and writes persistent records into the audit_logs table.
    """
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        req_id = getattr(request.state, "request_id", None) or request_id_ctx.get()
        app_name = client_app_ctx.get()
        user = username_ctx.get()
        client_ip = request.client.host if request.client else "unknown"

        # Capture and mask incoming request body
        req_body_bytes = await request.body()
        req_body_str = req_body_bytes.decode("utf-8", errors="ignore") if req_body_bytes else ""
        masked_req_body = mask_pii_string(req_body_str)

        # Restore body for downstream handlers
        async def receive():
            return {"type": "http.request", "body": req_body_bytes}
        request._receive = receive

        # Execute downstream request
        response: StarletteResponse = await call_next(request)
        duration_ms = int((time.time() - start_time) * 1000)

        # Capture response body
        res_body_bytes = b""
        async for chunk in response.body_iterator:
            res_body_bytes += chunk

        res_body_str = res_body_bytes.decode("utf-8", errors="ignore") if res_body_bytes else ""
        masked_res_body = mask_pii_string(res_body_str)

        # Log formatted audit line
        logger.info(
            f"AUDIT | Method={request.method} | Path={request.url.path} | Status={response.status_code} | "
            f"Duration={duration_ms}ms | ClientIP={client_ip} | ReqBody={masked_req_body[:300]} | ResBody={masked_res_body[:300]}"
        )

        # Persist audit record asynchronously/safely
        db = None
        try:
            db = SessionLocal()
            audit_entry = AuditLog(
                request_id=req_id,
                app_name=app_name,
                username=user,
                client_ip=client_ip,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                request_headers=mask_pii_data(dict(request.headers)),
                request_payload=masked_req_body,
                response_payload=masked_res_body
            )
            db.add(audit_entry)
            db.commit()
        except Exception as e:
            logger.debug(f"Audit log persistence bypassed: {e}")
        finally:
            if db:
                db.close()

        return Response(
            content=res_body_bytes,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type
        )
