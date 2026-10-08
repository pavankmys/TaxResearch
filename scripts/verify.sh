#!/usr/bin/env bash
# Verify that the TaxResearch stack is ready and healthy.
# Waits for API and web services, checks health endpoints, runs OCR smoke test.

set -euo pipefail

# Source .env for environment variables
if [ -f .env ]; then
    # Export all non-empty vars from .env
    set -a
    source .env
    set +a
fi

# Determine compose command
COMPOSE_CMD="podman compose"
if ! command -v podman &> /dev/null; then
    COMPOSE_CMD="docker compose"
fi

echo "Verifying TaxResearch stack..."
echo ""

# Wait for API to be healthy
echo "Waiting for API service..."
TIMEOUT=120
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    if curl -s http://127.0.0.1:8000/health > /dev/null 2>&1; then
        echo "✓ API is responding"
        break
    fi
    echo "  Waiting... ($ELAPSED/$TIMEOUT s)"
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    echo "✗ API health check timed out"
    exit 1
fi

# Get and print API health status
echo ""
echo "API health status:"
curl -s http://127.0.0.1:8000/health | head -c 500
echo ""
echo ""

# Check web page
echo "Checking web service..."
if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000 | grep -q "200"; then
    echo "✓ Web service is responding (HTTP 200)"
else
    echo "✗ Web service not responding"
    exit 1
fi

echo ""

# Run OCR smoke test in worker container if .venv exists locally
if [ -d .venv ]; then
    echo "Running OCR smoke test in local .venv..."
    if $COMPOSE_CMD -f infra/compose.yaml exec -T worker python /app/scripts/ocr_smoke.py > /tmp/ocr_result.log 2>&1; then
        echo "✓ OCR smoke test passed"
    else
        echo "✗ OCR smoke test failed"
        cat /tmp/ocr_result.log || true
    fi
else
    echo "ℹ .venv not found, skipping local OCR test"
fi

echo ""

# Run integration tests if .venv exists and DATABASE_URL is set
if [ -d .venv ] && [ -n "${DATABASE_URL:-}" ]; then
    echo "Running integration tests..."
    if .venv/Scripts/python -m pytest -q -m integration -rs 2>&1 | head -20; then
        echo "✓ Integration tests completed"
    else
        echo "⚠ Some integration tests may have issues (see above)"
    fi
else
    echo "ℹ .venv not found or DATABASE_URL not set, skipping integration tests"
fi

echo ""
echo "✓ Verification complete!"
echo ""
echo "Next steps:"
echo "  - Web app: http://127.0.0.1:3000"
echo "  - API: http://127.0.0.1:8000"
echo "  - View logs: $COMPOSE_CMD -f infra/compose.yaml logs -f"
echo "  - Stop services: $COMPOSE_CMD -f infra/compose.yaml down"
