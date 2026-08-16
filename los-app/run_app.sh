#!/usr/bin/env bash
# ==============================================================================
# Production-ready runner script for FastAPI Application (los-app)
# Supports full customization of Uvicorn feature flags via environment variables.
# ==============================================================================

set -e

# Change to the application directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ------------------------------------------------------------------------------
# Default Configuration & Explanation of Feature Flags
# ------------------------------------------------------------------------------

# HOST: Network interface to bind (0.0.0.0 listens on all interfaces, 127.0.0.1 for local only)
HOST="${HOST:-0.0.0.0}"

# PORT: TCP port on which the FastAPI server will listen
PORT="${PORT:-8000}"

# WORKERS: Number of worker processes (Recommended: (2 x $num_cores) + 1 for CPU-bound or I/O load)
# Note: When RELOAD is enabled, WORKERS is forced to 1 by Uvicorn.
WORKERS="${WORKERS:-1}"

# LOG_LEVEL: Logging level ('critical', 'error', 'warning', 'info', 'debug', 'trace')
LOG_LEVEL="${LOG_LEVEL:-info}"

# ACCESS_LOG: Enable or disable logging of every incoming HTTP request (true / false)
ACCESS_LOG="${ACCESS_LOG:-true}"

# RELOAD: Enable auto-reload on code change (set to true for development, false for production)
RELOAD="${RELOAD:-false}"

# TIMEOUT_KEEP_ALIVE: HTTP Keep-Alive timeout in seconds (prevents premature connection drops)
TIMEOUT_KEEP_ALIVE="${TIMEOUT_KEEP_ALIVE:-65}"

# LIMIT_CONCURRENCY: Maximum number of concurrent connections before issuing HTTP 503 (unset for unlimited)
LIMIT_CONCURRENCY="${LIMIT_CONCURRENCY:-}"

# LIMIT_MAX_REQUESTS: Maximum requests a worker will service before restarting (helps mitigate memory leaks)
LIMIT_MAX_REQUESTS="${LIMIT_MAX_REQUESTS:-}"

# PROXY_HEADERS: Enable X-Forwarded-For / X-Forwarded-Proto headers when running behind a Reverse Proxy (Nginx/Traefik)
PROXY_HEADERS="${PROXY_HEADERS:-true}"

# FORWARDED_ALLOW_IPS: Trusted proxy IPs permitted to set proxy headers ('*' for any, or specific CIDR)
FORWARDED_ALLOW_IPS="${FORWARDED_ALLOW_IPS:-*}"

# BACKLOG: Maximum number of connections to hold in the TCP listen queue
BACKLOG="${BACKLOG:-2048}"

# APP_MODULE: ASGI application import path
APP_MODULE="app.main:app"

# ------------------------------------------------------------------------------
# Assemble Uvicorn Command Arguments
# ------------------------------------------------------------------------------

CMD_ARGS=(
  "$APP_MODULE"
  "--host" "$HOST"
  "--port" "$PORT"
  "--log-level" "$LOG_LEVEL"
  "--timeout-keep-alive" "$TIMEOUT_KEEP_ALIVE"
  "--backlog" "$BACKLOG"
)

if [ "$RELOAD" = "true" ]; then
  CMD_ARGS+=("--reload")
else
  CMD_ARGS+=("--workers" "$WORKERS")
fi

if [ "$ACCESS_LOG" = "true" ]; then
  CMD_ARGS+=("--access-log")
else
  CMD_ARGS+=("--no-access-log")
fi

if [ "$PROXY_HEADERS" = "true" ]; then
  CMD_ARGS+=("--proxy-headers" "--forwarded-allow-ips" "$FORWARDED_ALLOW_IPS")
fi

if [ -n "$LIMIT_CONCURRENCY" ]; then
  CMD_ARGS+=("--limit-concurrency" "$LIMIT_CONCURRENCY")
fi

if [ -n "$LIMIT_MAX_REQUESTS" ]; then
  CMD_ARGS+=("--limit-max-requests" "$LIMIT_MAX_REQUESTS")
fi

echo "================================================================================"
echo " Starting FastAPI Server (los-app)..."
echo " Host: $HOST | Port: $PORT | Workers: $WORKERS | Log Level: $LOG_LEVEL | Reload: $RELOAD"
echo "================================================================================"

exec python -m uvicorn "${CMD_ARGS[@]}"
