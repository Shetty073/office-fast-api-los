import json
import logging
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response as StarletteResponse
from app.core.security import decode_access_token, encrypt_payload, decrypt_payload

logger = logging.getLogger(__name__)

class PayloadEncryptionMiddleware(BaseHTTPMiddleware):
    """
    AES-256-GCM Request/Response Encryption Middleware.
    Inspects authenticated user's JWT claims:
    - If user has enable_encryption=True, incoming request ciphertext is decrypted before route handlers,
      and outgoing JSON responses are encrypted.
    - If enable_encryption=False, requests and responses remain standard plaintext JSON.
    """
    async def dispatch(self, request: Request, call_next):
        # 1. Determine if current caller has encryption enabled from JWT claims
        auth_header = request.headers.get("Authorization")
        requires_encryption = False
        encryption_key = None

        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = decode_access_token(token)
            if payload and payload.get("enable_encryption") and payload.get("encryption_key"):
                requires_encryption = True
                encryption_key = payload["encryption_key"]

        request.state.requires_encryption = requires_encryption
        request.state.encryption_key = encryption_key

        # 2. Decrypt incoming payload if user has encryption enabled
        if requires_encryption and request.method in ["POST", "PUT", "PATCH"]:
            body_bytes = await request.body()
            if body_bytes:
                try:
                    encrypted_data = json.loads(body_bytes.decode("utf-8"))
                    if isinstance(encrypted_data, dict) and "ciphertext" in encrypted_data and "iv" in encrypted_data:
                        decrypted_text = decrypt_payload(encrypted_data, encryption_key)
                        decrypted_bytes = decrypted_text.encode("utf-8")
                        
                        # Replace ASGI receive stream with decrypted body
                        async def receive():
                            return {"type": "http.request", "body": decrypted_bytes}
                        request._receive = receive
                    else:
                        return JSONResponse(
                            status_code=400,
                            content={"detail": "Payload encryption is enabled for this account. Request must be formatted as {'ciphertext': '...', 'iv': '...', 'tag': '...'}"}
                        )
                except Exception as e:
                    logger.error(f"Payload decryption failed: {e}")
                    return JSONResponse(
                        status_code=400,
                        content={"detail": f"Decryption failed: {str(e)}"}
                    )

        # 3. Proceed to endpoint execution
        response: StarletteResponse = await call_next(request)

        # 4. Encrypt outgoing response if user has encryption enabled and response is JSON
        if requires_encryption and response.status_code < 400:
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                # Capture body from streaming response
                response_body = b""
                async for chunk in response.body_iterator:
                    response_body += chunk
                
                try:
                    plaintext = response_body.decode("utf-8")
                    encrypted_res = encrypt_payload(plaintext, encryption_key)
                    return JSONResponse(
                        status_code=response.status_code,
                        content=encrypted_res,
                        headers=dict(response.headers)
                    )
                except Exception as e:
                    logger.error(f"Response encryption failed: {e}")

        return response
