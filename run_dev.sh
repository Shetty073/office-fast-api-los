#!/bin/bash
# Local development server launch utility

# Activate virtual environment if present
if [ -d ".venv" ]; then
    echo "Activating virtual environment..."
    source .venv/bin/activate
fi

echo "Starting SCF LOS backend dev server on http://localhost:8000..."
uvicorn main:app --reload --host 0.0.0.0 --port 8000
