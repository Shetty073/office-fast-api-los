#!/usr/bin/env bash
# ==============================================================================
# Production-ready runner script for FastAPI Application (los-app)
# Supports full customization of Uvicorn feature flags via environment variables.
# ==============================================================================

# Change to the application directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ------------------------------------------------------------------------------
# Default Configuration & Explanation of Feature Flags
# ------------------------------------------------------------------------------

# HOST: Network interface to bind (0.0.0.0 listens on all interfaces, 127.0.0.1 for local only)
export HOST="${HOST:-0.0.0.0}"

# PORT: TCP port on which the FastAPI server will listen
export PORT="${PORT:-8000}"

# WORKERS: Number of worker processes (Recommended: (2 x $num_cores) + 1 for CPU-bound or I/O load)
# Note: When RELOAD is enabled, WORKERS is forced to 1 by Uvicorn.
export WORKERS="${WORKERS:-1}"

# LOG_LEVEL: Logging level ('critical', 'error', 'warning', 'info', 'debug', 'trace')
export LOG_LEVEL="${LOG_LEVEL:-info}"

# ACCESS_LOG: Enable or disable logging of every incoming HTTP request (true / false)
export ACCESS_LOG="${ACCESS_LOG:-true}"

# RELOAD: Enable auto-reload on code change (set to true for development, false for production)
export RELOAD="${RELOAD:-false}"

# TIMEOUT_KEEP_ALIVE: HTTP Keep-Alive timeout in seconds (prevents premature connection drops)
export TIMEOUT_KEEP_ALIVE="${TIMEOUT_KEEP_ALIVE:-65}"

# LIMIT_CONCURRENCY: Maximum number of concurrent connections before issuing HTTP 503 (unset for unlimited)
export LIMIT_CONCURRENCY="${LIMIT_CONCURRENCY:-}"

# LIMIT_MAX_REQUESTS: Maximum requests a worker will service before restarting (helps mitigate memory leaks)
export LIMIT_MAX_REQUESTS="${LIMIT_MAX_REQUESTS:-}"

# PROXY_HEADERS: Enable X-Forwarded-For / X-Forwarded-Proto headers when running behind a Reverse Proxy (Nginx/Traefik)
export PROXY_HEADERS="${PROXY_HEADERS:-true}"

# FORWARDED_ALLOW_IPS: Trusted proxy IPs permitted to set proxy headers ('*' for any, or specific CIDR)
export FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}"

# BACKLOG: Maximum number of connections to hold in the TCP listen queue
export BACKLOG="${BACKLOG:-2048}"

# APP_MODULE: ASGI application import path
export APP_MODULE="app.main:app"

# Detect Python executable
if [ -f "../.venv/Scripts/python.exe" ]; then
  PYTHON_EXE="../.venv/Scripts/python.exe"
elif [ -f ".venv/Scripts/python.exe" ]; then
  PYTHON_EXE=".venv/Scripts/python.exe"
else
  PYTHON_EXE="python"
fi

echo "================================================================================"
echo " Starting FastAPI Server (los-app)..."
echo " Host: $HOST | Port: $PORT | Workers: $WORKERS | Log Level: $LOG_LEVEL | Reload: $RELOAD"
echo "================================================================================"

exec "$PYTHON_EXE" -c "
import os, sys, uvicorn

host = os.getenv('HOST', '0.0.0.0')
port = int(os.getenv('PORT', '8000'))
reload = os.getenv('RELOAD', 'false').lower() == 'true'
workers = int(os.getenv('WORKERS', '1')) if not reload else 1
log_level = os.getenv('LOG_LEVEL', 'info')
access_log = os.getenv('ACCESS_LOG', 'true').lower() == 'true'
timeout_keep_alive = int(os.getenv('TIMEOUT_KEEP_ALIVE', '65'))
backlog = int(os.getenv('BACKLOG', '2048'))
proxy_headers = os.getenv('PROXY_HEADERS', 'true').lower() == 'true'
forwarded_allow_ips = os.getenv('FORWARDED_ALLOW_IPS', '*')

limit_concurrency = int(os.getenv('LIMIT_CONCURRENCY')) if os.getenv('LIMIT_CONCURRENCY') else None
limit_max_requests = int(os.getenv('LIMIT_MAX_REQUESTS')) if os.getenv('LIMIT_MAX_REQUESTS') else None

uvicorn.run(
    'app.main:app',
    host=host,
    port=port,
    reload=reload,
    workers=workers,
    log_level=log_level,
    access_log=access_log,
    timeout_keep_alive=timeout_keep_alive,
    backlog=backlog,
    proxy_headers=proxy_headers,
    forwarded_allow_ips=forwarded_allow_ips,
    limit_concurrency=limit_concurrency,
    limit_max_requests=limit_max_requests
)
"
