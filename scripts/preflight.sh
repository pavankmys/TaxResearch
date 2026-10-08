#!/usr/bin/env bash
# Preflight checks before running containers.
# Verifies .env exists and contains no 'change-me' values or empty required variables.
# Exits non-zero with a clear message if any check fails.

set -euo pipefail

# Check .env exists
if [ ! -f .env ]; then
    echo "ERROR: .env file not found"
    echo "Create it with: cp .env.example .env"
    exit 1
fi

echo "✓ .env file found"

# Check for change-me values
if grep -q "change-me" .env; then
    echo "ERROR: .env contains 'change-me' placeholder values"
    echo "Please edit .env and replace all 'change-me' values with actual values"
    exit 1
fi

echo "✓ No 'change-me' placeholders in .env"

# Check required variables are not empty
required_vars=(
    "POSTGRES_USER"
    "POSTGRES_PASSWORD"
    "POSTGRES_DB"
    "DATABASE_URL"
    "S3_ENDPOINT_URL"
    "S3_ACCESS_KEY"
    "S3_SECRET_KEY"
    "S3_BUCKET"
    "JWT_SECRET"
    "LOG_LEVEL"
)

for var in "${required_vars[@]}"; do
    value=$(grep "^${var}=" .env | cut -d'=' -f2- || echo "")
    if [ -z "$value" ]; then
        echo "ERROR: Required variable $var is empty in .env"
        exit 1
    fi
done

echo "✓ All required variables are set"
echo "✓ Preflight checks passed"
