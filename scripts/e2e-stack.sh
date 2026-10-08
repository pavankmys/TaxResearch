#!/usr/bin/env bash
# Start the local stack for the Playwright end-to-end tests, or stop it.
#
#   scripts/e2e-stack.sh         migrate, create the test users, start API, worker and web
#   scripts/e2e-stack.sh stop    stop the processes started by the last run
#
# Needs DATABASE_URL for a Postgres database that may be migrated and filled with test data.
# Optional: E2E_PASSWORD (test users' password), JWT_SECRET (random when unset),
# PYTHON (Python with the API and worker installed; default: python).
# Logs and the PID file are in .e2e/ at the repository root.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$ROOT/apps/api"
WORKER_DIR="$ROOT/apps/worker"
WEB_DIR="$ROOT/apps/web"
STATE_DIR="$ROOT/.e2e"
PID_FILE="$STATE_DIR/pids"
LOG_DIR="$STATE_DIR/logs"
PYTHON_BIN="${PYTHON:-python}"
E2E_PASSWORD="${E2E_PASSWORD:-e2e-only-password-2026}"
API_URL="http://localhost:8000"
WEB_URL="http://localhost:3000"

kill_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

stop_stack() {
  if [ -f "$PID_FILE" ]; then
    while read -r name pid; do
      if [ -n "${pid:-}" ]; then
        echo "stopping $name ($pid)"
        kill_tree "$pid"
      fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi
}

wait_for_url() {
  local url="$1" seconds="$2" i
  for ((i = 0; i < seconds; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "ready: $url"
      return 0
    fi
    sleep 1
  done
  echo "timed out waiting for $url (logs in $LOG_DIR)" >&2
  return 1
}

create_user() {
  local email="$1" display_name="$2" role="$3" output status
  set +e
  output="$(cd "$API_DIR" && TAXRESEARCH_PASSWORD="$E2E_PASSWORD" "$PYTHON_BIN" -m app.cli create-user \
    --email "$email" --display-name "$display_name" --role "$role" 2>&1)"
  status=$?
  set -e
  if [ "$status" -eq 0 ]; then
    echo "created $email ($role)"
  elif echo "$output" | grep -q "already exists"; then
    echo "exists $email"
  else
    echo "$output" >&2
    return 1
  fi
}

start_stack() {
  : "${DATABASE_URL:?DATABASE_URL must point at the test Postgres database}"
  export DATABASE_URL
  JWT_SECRET="${JWT_SECRET:-$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_hex(32))')}"
  export JWT_SECRET

  stop_stack
  mkdir -p "$LOG_DIR" "$STATE_DIR/store" "$STATE_DIR/watch"
  : > "$PID_FILE"
  trap 'echo "start failed; stopping the stack" >&2; stop_stack; exit 1' ERR

  echo "migrating the database"
  (cd "$API_DIR" && "$PYTHON_BIN" -m alembic upgrade head) > "$LOG_DIR/migrate.log" 2>&1

  create_user admin@e2e.test "E2E Admin" platform_admin
  create_user editor@e2e.test "E2E Content Editor" platform_content_editor
  create_user pro@e2e.test "E2E Professional" professional

  echo "starting the API"
  (cd "$API_DIR" && exec "$PYTHON_BIN" -m uvicorn --factory app.main:create_app --port 8000) \
    > "$LOG_DIR/api.log" 2>&1 &
  echo "api $!" >> "$PID_FILE"

  echo "starting the worker"
  (cd "$WORKER_DIR" && OBJECT_STORE=local LOCAL_STORE_PATH="$STATE_DIR/store" \
    WATCH_FOLDER="$STATE_DIR/watch" exec "$PYTHON_BIN" -m worker) \
    > "$LOG_DIR/worker.log" 2>&1 &
  echo "worker $!" >> "$PID_FILE"

  echo "building the web app"
  (cd "$WEB_DIR" && npm run build) > "$LOG_DIR/web-build.log" 2>&1

  echo "starting the web app"
  (cd "$WEB_DIR" && API_URL="$API_URL" COOKIE_SECURE=false npm run start) \
    > "$LOG_DIR/web.log" 2>&1 &
  echo "web $!" >> "$PID_FILE"

  wait_for_url "$API_URL/health" 60
  wait_for_url "$WEB_URL/api/health" 120

  trap - ERR
  echo "stack is up. Run: npx playwright test (in apps/web). Stop with: scripts/e2e-stack.sh stop"
}

case "${1:-start}" in
  start) start_stack ;;
  stop) stop_stack; echo "stack stopped" ;;
  *)
    echo "usage: scripts/e2e-stack.sh [start|stop]" >&2
    exit 2
    ;;
esac
