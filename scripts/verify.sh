#!/usr/bin/env bash
# Check that a running TaxResearch stack is healthy. Exits non-zero if any check fails.
#
# Checks: API /ready (200 only when the database answers), web /api/health, worker heartbeat.
# Used by deploy.sh on the VM, and by hand on a development machine.
#
# Settings (environment):
#   BASE_API            default http://127.0.0.1:8000
#   BASE_WEB            default http://127.0.0.1:3000
#   CONTAINER_WORKER    default taxresearch-worker
#   COMPOSE_RUNTIME     podman (default) or docker
#   VERIFY_TIMEOUT      seconds to wait for the API, default 120
#   SKIP_WORKER_CHECK   1 = do not check the worker (for a stack without one)
#   VERIFY_EXTRAS       1 = also run the OCR smoke test inside the worker container

set -euo pipefail

BASE_API="${BASE_API:-http://127.0.0.1:8000}"
BASE_WEB="${BASE_WEB:-http://127.0.0.1:3000}"
CONTAINER_WORKER="${CONTAINER_WORKER:-taxresearch-worker}"
COMPOSE_RUNTIME="${COMPOSE_RUNTIME:-podman}"
VERIFY_TIMEOUT="${VERIFY_TIMEOUT:-120}"
SKIP_WORKER_CHECK="${SKIP_WORKER_CHECK:-0}"
VERIFY_EXTRAS="${VERIFY_EXTRAS:-0}"

http_code() {
	curl -s -o /dev/null --max-time 5 -w '%{http_code}' "$1" 2>/dev/null || true
}

echo "Verifying the stack (API ${BASE_API}, web ${BASE_WEB})"

# 1. API: wait for /ready
elapsed=0
while true; do
	code="$(http_code "${BASE_API}/ready")"
	if [ "$code" = "200" ]; then
		echo "ok: API /ready"
		break
	fi
	if [ "$elapsed" -ge "$VERIFY_TIMEOUT" ]; then
		echo "FAILED: API /ready returned '${code:-none}' after ${VERIFY_TIMEOUT}s (503 means the database is unreachable)" >&2
		exit 1
	fi
	sleep 5
	elapsed=$((elapsed + 5))
done

# 2. Web
code="$(http_code "${BASE_WEB}/api/health")"
if [ "$code" != "200" ]; then
	echo "FAILED: web /api/health returned '${code:-none}'" >&2
	exit 1
fi
echo "ok: web /api/health"

# 3. Worker heartbeat
if [ "$SKIP_WORKER_CHECK" = "1" ]; then
	echo "skipped: worker heartbeat (SKIP_WORKER_CHECK=1)"
elif "$COMPOSE_RUNTIME" exec "$CONTAINER_WORKER" python -m worker.heartbeat --check >/dev/null 2>&1; then
	echo "ok: worker heartbeat"
else
	echo "FAILED: worker heartbeat (is the container '${CONTAINER_WORKER}' running?)" >&2
	exit 1
fi

# 4. Optional OCR smoke test
if [ "$VERIFY_EXTRAS" = "1" ]; then
	log="$(mktemp)"
	trap 'rm -f "$log"' EXIT
	if "$COMPOSE_RUNTIME" exec "$CONTAINER_WORKER" python /app/scripts/ocr_smoke.py >"$log" 2>&1; then
		echo "ok: OCR smoke test"
	else
		echo "FAILED: OCR smoke test" >&2
		cat "$log" >&2
		exit 1
	fi
fi

echo "All checks passed."
