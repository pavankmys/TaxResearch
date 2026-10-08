#!/usr/bin/env bash
# Start the TaxResearch stack using podman-compose or docker-compose.
# Runs preflight checks, then starts containers in the background with --build.

set -euo pipefail

# Run preflight checks
echo "Running preflight checks..."
bash scripts/preflight.sh

# Determine which compose tool to use
COMPOSE_CMD="podman compose"
if ! command -v podman &> /dev/null; then
    echo "ℹ podman not found, trying docker compose"
    COMPOSE_CMD="docker compose"
fi

echo "✓ Using: $COMPOSE_CMD"
echo ""

# Start containers
echo "Starting TaxResearch stack..."
$COMPOSE_CMD -f infra/compose.yaml up --build -d

echo "✓ Containers started in background"
echo ""
echo "Services are starting. Check status with:"
echo "  $COMPOSE_CMD -f infra/compose.yaml logs -f"
echo ""
echo "Once ready, run verify.sh to check health:"
echo "  bash scripts/verify.sh"
