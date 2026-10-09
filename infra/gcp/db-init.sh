#!/usr/bin/env bash
# One-time database setup for Cloud SQL, run on the VM (it is inside the VPC; Cloud Shell is not).
#
#   db-init.sh            create the application role and database, enable the four extensions
#   db-init.sh --check    exit 0 only if the application role can connect and all four exist
#
# Reads two secrets from Secret Manager: taxresearch-env (the application settings, including
# DATABASE_URL) and taxresearch-db-admin (the Cloud SQL 'postgres' password). Runs psql from the
# postgres:16 container image. No password is printed or put on a command line: they travel in
# environment variables, passed to the container by name only. Safe to run again.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PSQL_IMAGE="docker.io/library/postgres:16"
MODE="init"
if [ "${1:-}" = "--check" ]; then
	MODE="check"
fi

PROJECT_ARGS=()
if [ -n "${GCP_PROJECT:-}" ]; then
	PROJECT_ARGS=(--project="$GCP_PROJECT")
fi

die() {
	echo "ERROR: $*" >&2
	exit 1
}

for tool in gcloud podman python3; do
	command -v "$tool" >/dev/null 2>&1 || die "$tool is not installed"
done

env_text="$(gcloud secrets versions access latest --secret=taxresearch-env "${PROJECT_ARGS[@]}" 2>/dev/null)" ||
	die "could not read the taxresearch-env secret (does the VM's service account have access?)"

# Host, port, user, password and database name from DATABASE_URL, separated by NUL characters.
parts=()
while IFS= read -r -d '' item; do
	parts+=("$item")
done < <(printf '%s\n' "$env_text" | python3 -c '
import sys
import urllib.parse

values = {}
for line in sys.stdin.read().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
url = urllib.parse.urlsplit(values["DATABASE_URL"])
fields = [
    url.hostname or "",
    str(url.port or 5432),
    urllib.parse.unquote(url.username or ""),
    urllib.parse.unquote(url.password or ""),
    (url.path or "/").lstrip("/"),
]
sys.stdout.write("\0".join(fields) + "\0")
') || die "could not read DATABASE_URL from the taxresearch-env secret"
unset env_text

[ "${#parts[@]}" -eq 5 ] || die "DATABASE_URL is not in the expected form"
db_host="${parts[0]}"
db_port="${parts[1]}"
export DB_APP_USER="${parts[2]}"
export DB_APP_PASSWORD="${parts[3]}"
export DB_NAME="${parts[4]}"
unset parts
[ -n "$db_host" ] && [ -n "$DB_APP_USER" ] && [ -n "$DB_APP_PASSWORD" ] && [ -n "$DB_NAME" ] ||
	die "DATABASE_URL is missing the host, user, password or database name"

if [ "$MODE" = "check" ]; then
	export PGPASSWORD="$DB_APP_PASSWORD"
	count="$(podman run --rm --network=host -e PGPASSWORD -e PGSSLMODE=require "$PSQL_IMAGE" \
		psql -h "$db_host" -p "$db_port" -U "$DB_APP_USER" -d "$DB_NAME" -At \
		-c "SELECT count(*) FROM pg_extension WHERE extname IN ('citext','ltree','pg_trgm','btree_gist')" \
		2>/dev/null)" || {
		echo "The application role cannot connect yet (expected on the first deploy)." >&2
		exit 1
	}
	if [ "$count" = "4" ]; then
		echo "Database ready: the application role connects and all 4 extensions exist."
		exit 0
	fi
	echo "Only ${count:-0} of the 4 extensions exist." >&2
	exit 1
fi

admin_password="$(gcloud secrets versions access latest --secret=taxresearch-db-admin "${PROJECT_ARGS[@]}" 2>/dev/null)" ||
	die "could not read the taxresearch-db-admin secret"
[ -n "$admin_password" ] || die "the taxresearch-db-admin secret is empty"
export PGPASSWORD="$admin_password"
unset admin_password

echo "Setting up the database (role, database, extensions) as the postgres user..."

podman run --rm --network=host \
	-e PGPASSWORD -e PGSSLMODE=require -e DB_APP_USER -e DB_APP_PASSWORD -e DB_NAME \
	-v "$SCRIPT_DIR/db-init.sql:/db-init.sql:ro" \
	"$PSQL_IMAGE" \
	psql -h "$db_host" -p "$db_port" -U postgres -d postgres -v ON_ERROR_STOP=1 -q -f /db-init.sql

podman run --rm -i --network=host \
	-e PGPASSWORD -e PGSSLMODE=require \
	"$PSQL_IMAGE" \
	psql -h "$db_host" -p "$db_port" -U postgres -d "$DB_NAME" -v ON_ERROR_STOP=1 -q <<'SQL'
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gist;
SQL

echo "Database setup finished."
