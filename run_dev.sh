#!/usr/bin/env bash
# Root development runner - Launches FastAPI development server
cd "$(dirname "$0")/los-app"
RELOAD=true WORKERS=1 LOG_LEVEL=debug ./run_app.sh
