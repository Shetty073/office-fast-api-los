#!/usr/bin/env bash
# Runs test suites for both los-app and orchestration-service with coverage
set -e

echo "=== 1. Running los-app Test Suite ==="
cd "$(dirname "$0")/los-app"
python -m pytest --cov=app --cov-report=term-missing tests

echo ""
echo "=== 2. Running orchestration-service Test Suite ==="
cd "../orchestration-service"
python -m pytest --cov=. --cov-report=term-missing tests

echo ""
echo "All tests passed successfully!"
