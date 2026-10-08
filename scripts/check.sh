#!/bin/bash
# Code quality check script for Linux/macOS
# Runs ruff, mypy, and pytest
# Fails on first error

set -e

echo "TaxResearch: Code quality checks"
echo "================================"

# Check if .venv exists
if [ ! -d ".venv" ]; then
    echo "Error: .venv not found. Run: python -m venv .venv" >&2
    exit 1
fi

PYTHON="./.venv/bin/python"
RUFF="./.venv/bin/ruff"
MYPY="./.venv/bin/mypy"
PYTEST="./.venv/bin/pytest"

# 1. Ruff lint
echo ""
echo "Running ruff check..."
$RUFF check .

# 2. Ruff format check
echo ""
echo "Running ruff format check..."
$RUFF format --check .

# 3. MyPy type check
echo ""
echo "Running mypy..."
$MYPY

# 4. Pytest (exclude integration tests)
echo ""
echo "Running pytest..."
$PYTEST -m "not integration" --tb=short

# 5. Web linting (if package.json exists)
if [ -f "apps/web/package.json" ]; then
    echo ""
    echo "Running web linting..."
    npm --prefix apps/web run lint
fi

# 6. Web type check (if package.json exists)
if [ -f "apps/web/package.json" ]; then
    echo ""
    echo "Running web typecheck..."
    npm --prefix apps/web run typecheck
fi

echo ""
echo "✓ All checks passed"
exit 0
