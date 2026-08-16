#!/usr/bin/env bash
# ==============================================================================
# Production-ready runner script for Standalone ARQ Worker (orchestration-service)
# Supports full customization of ARQ Worker settings via environment variables.
# ==============================================================================

set -e

# Change to the orchestration-service directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ------------------------------------------------------------------------------
# Default Configuration & Explanation of Feature Flags
# ------------------------------------------------------------------------------

# REDIS_HOST: Redis server host
export REDIS_HOST="${REDIS_HOST:-localhost}"

# REDIS_PORT: Redis server port
export REDIS_PORT="${REDIS_PORT:-6379}"

# REDIS_PASSWORD: Redis authentication password (optional)
export REDIS_PASSWORD="${REDIS_PASSWORD:-}"

# REDIS_DATABASE: Redis DB index (0-15)
export REDIS_DATABASE="${REDIS_DATABASE:-0}"

# FASTAPI_BASE_URL: Target FastAPI API address to dispatch step calls to
export FASTAPI_BASE_URL="${FASTAPI_BASE_URL:-http://localhost:8000}"

# MAX_JOBS: Maximum concurrent tasks this worker will execute simultaneously
export MAX_JOBS="${MAX_JOBS:-20}"

# JOB_TIMEOUT: Global job execution timeout in seconds before marking failed
export JOB_TIMEOUT="${JOB_TIMEOUT:-300}"

# KEEP_RESULT: Number of seconds completed job results are kept in Redis
export KEEP_RESULT="${KEEP_RESULT:-3600}"

# POLL_DELAY: Delay between polling Redis for new jobs in seconds
export POLL_DELAY="${POLL_DELAY:-0.5}"

# QUEUE_NAME: Name of the Redis queue to process
export QUEUE_NAME="${QUEUE_NAME:-arq:queue}"

# BURST: If true, worker runs until queue is empty and then exits (useful for batch jobs/tests)
BURST="${BURST:-false}"

# WORKER_SETTINGS: ARQ worker configuration module import path
WORKER_SETTINGS="worker.WorkerSettings"

# ------------------------------------------------------------------------------
# Assemble ARQ Command Arguments
# ------------------------------------------------------------------------------

CMD_ARGS=(
  "$WORKER_SETTINGS"
)

if [ "$BURST" = "true" ]; then
  CMD_ARGS+=("--burst")
fi

echo "================================================================================"
echo " Starting ARQ Orchestration Worker..."
echo " Redis: $REDIS_HOST:$REDIS_PORT (DB: $REDIS_DATABASE) | Max Jobs: $MAX_JOBS"
echo " FastAPI Base URL: $FASTAPI_BASE_URL | Queue: $QUEUE_NAME"
echo "================================================================================"

exec python -m arq "${CMD_ARGS[@]}"
