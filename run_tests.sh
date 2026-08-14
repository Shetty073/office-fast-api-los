#!/bin/bash
# Test execution runner with code coverage calculations

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "Setting SQLite test database..."
export DATABASE_URL="sqlite:///test_los.db"

echo "Executing unit tests..."
pytest --cov=. --cov-report=term-missing -vv tests/
