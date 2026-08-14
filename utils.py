from typing import Dict, Any, Optional
import time
import requests
import json
from sqlalchemy.orm import Session
from database import SessionLocal
from models import APILog

def get_by_path(d: Any, path: str) -> Any:
    """
    Resolve a dot-notated path in a nested dictionary/list.
    Example: get_by_path({"profile": {"email": "john@example.com"}}, "profile.email") -> "john@example.com"
    """
    if not path:
        return d
    parts = path.split('.')
    curr = d
    for part in parts:
        if isinstance(curr, dict) and part in curr:
            curr = curr[part]
        elif isinstance(curr, list):
            try:
                idx = int(part)
                curr = curr[idx]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return curr

def set_by_path(d: Dict[str, Any], path: str, value: Any) -> None:
    """
    Set a value in a nested dictionary at a dot-notated path,
    creating parent dictionaries as needed.
    Example: set_by_path({}, "profile.email", "john@example.com") -> {"profile": {"email": "john@example.com"}}
    """
    if not path:
        return
    parts = path.split('.')
    curr = d
    for part in parts[:-1]:
        if part not in curr or not isinstance(curr[part], dict):
            curr[part] = {}
        curr = curr[part]
    curr[parts[-1]] = value


class SecretResolver:
    @staticmethod
    def get_auth_headers(service_name: str) -> Dict[str, str]:
        """
        Retrieve authentication headers for a given service.
        In production, this would integrate with Vault or AWS Secrets Manager.
        Here we check environment variables: e.g. TODO_SERVICE_API_KEY.
        If missing, we return a mock authorization header.
        """
        import os
        env_key = f"{service_name.upper()}_API_KEY"
        api_key = os.getenv(env_key)
        if api_key:
            return {"Authorization": f"Bearer {api_key}"}
        return {"Authorization": f"Bearer mock-key-for-{service_name}"}


class APIClient:
    """
    Utility wrapper around python requests library.
    Exposes requests functions and logs every request & response detail into the database.
    """
    def __init__(self, service_name: str, execution_id: Optional[str] = None, timeout: float = 10.0):
        self.service_name = service_name
        self.execution_id = execution_id
        self.default_timeout = timeout

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        start_time = time.time()

        # Inject default timeout if not specified
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.default_timeout

        # Inject authentication headers if not specified
        req_headers = kwargs.get("headers", {})
        if req_headers is None:
            req_headers = {}
        else:
            req_headers = dict(req_headers)
        if "Authorization" not in req_headers:
            auth_headers = SecretResolver.get_auth_headers(self.service_name)
            req_headers.update(auth_headers)
            kwargs["headers"] = req_headers

        # Extract payload information safely for logs
        req_body = None
        if "json" in kwargs:
            req_body = json.dumps(kwargs["json"])
        elif "data" in kwargs:
            req_body = str(kwargs["data"])
        elif "params" in kwargs:
            req_body = json.dumps(kwargs["params"])

        response_status = None
        res_headers = {}
        res_body = None

        try:
            # Perform standard requests execution
            response = requests.request(method, url, **kwargs)
            response_status = response.status_code
            res_headers = dict(response.headers)
            res_body = response.text
            return response
        except Exception as e:
            response_status = 0
            res_body = f"Connection Exception: {str(e)}"
            raise e
        finally:
            duration_ms = int((time.time() - start_time) * 1000)

            # Persistent DB logging
            db = None
            try:
                db = SessionLocal()
                log_entry = APILog(
                    execution_id=self.execution_id,
                    service_name=self.service_name,
                    method=method.upper(),
                    url=url,
                    request_headers=dict(req_headers) if req_headers else {},
                    request_body=req_body,
                    response_status=response_status,
                    response_headers=res_headers,
                    response_body=res_body,
                    duration_ms=duration_ms
                )
                db.add(log_entry)
                db.commit()
            except Exception as log_err:
                # Never crash the API call if database logging fails
                print(f"API Logger Exception: {log_err}")
            finally:
                if db:
                    db.close()

    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs) -> requests.Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs) -> requests.Response:
        return self.request("DELETE", url, **kwargs)

    def patch(self, url: str, **kwargs) -> requests.Response:
        return self.request("PATCH", url, **kwargs)
