#!/usr/bin/env bash
# Deploy TaxResearch to /opt/taxresearch on Compute Engine VM.
# Usage: deploy.sh <tag> | --rollback [--dry-run]
# Fetches .env from Secret Manager, validates it, pulls images, runs migrations,
# brings up services, verifies health, and rolls back on failure.

set -euo pipefail

# Configuration
TAXRESEARCH_DIR="${TAXRESEARCH_DIR:-/opt/taxresearch}"
DEPLOY_LOG="$TAXRESEARCH_DIR/deploy.log"
TAG_FILE_CURRENT="$TAXRESEARCH_DIR/current_tag"
TAG_FILE_PREVIOUS="$TAXRESEARCH_DIR/previous_tag"
COMPOSE_FILE="$TAXRESEARCH_DIR/compose.gcp.yaml"
ENV_FILE="$TAXRESEARCH_DIR/.env"
ENV_FILE_NEW="$TAXRESEARCH_DIR/.env.new"
VERIFY_SCRIPT="$TAXRESEARCH_DIR/verify.sh"
DB_INIT_SCRIPT="$TAXRESEARCH_DIR/db-init.sh"
VERIFY_TIMEOUT="${VERIFY_TIMEOUT:-180}"
DRY_RUN=0
DO_ROLLBACK=0
PROJECT_ARGS=()
if [ -n "${GCP_PROJECT:-}" ]; then
	PROJECT_ARGS=(--project="$GCP_PROJECT")
fi

mkdir -p "$TAXRESEARCH_DIR"

# Logging helper: append with timestamp
log() {
	echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$DEPLOY_LOG"
}

# Log errors without printing the message twice
logerr() {
	echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >> "$DEPLOY_LOG"
	echo "ERROR: $*" >&2
}

# Validate tag format
validate_tag() {
	local tag="$1"
	if ! [[ "$tag" =~ ^[A-Za-z0-9._-]{1,128}$ ]]; then
		logerr "Tag format invalid: '$tag'. Expected ^[A-Za-z0-9._-]{1,128}$"
		return 1
	fi
}

# Parse arguments
if [ $# -eq 0 ]; then
	logerr "Usage: $0 <tag> | --rollback [--dry-run]"
	exit 1
fi

if [ "$1" = "--rollback" ]; then
	DO_ROLLBACK=1
	shift
	if [ "$#" -gt 0 ] && [ "$1" = "--dry-run" ]; then
		DRY_RUN=1
	fi
elif [ "$1" = "--dry-run" ]; then
	DRY_RUN=1
	if [ "$#" -gt 1 ]; then
		TAG="$2"
		validate_tag "$TAG" || exit 1
	fi
else
	TAG="$1"
	validate_tag "$TAG" || exit 1
	if [ "$#" -gt 1 ] && [ "$2" = "--dry-run" ]; then
		DRY_RUN=1
	fi
fi

# Set XDG_RUNTIME_DIR if not already set (needed for rootless Podman)
if [ -z "${XDG_RUNTIME_DIR:-}" ]; then
	XDG_RUNTIME_DIR="/run/user/$(id -u)"
	export XDG_RUNTIME_DIR
fi

log "Starting deploy (DRY_RUN=$DRY_RUN, ROLLBACK=$DO_ROLLBACK)"

# ==============================================================================
# ROLLBACK MODE
# ==============================================================================
if [ "$DO_ROLLBACK" -eq 1 ]; then
	if [ ! -f "$TAG_FILE_PREVIOUS" ]; then
		logerr "No previous tag to rollback to"
		exit 1
	fi
	TAG=$(cat "$TAG_FILE_PREVIOUS")
	log "Rolling back to tag: $TAG"
	if [ "$DRY_RUN" -eq 1 ]; then
		log "[DRY-RUN] Would redeploy with TAG=$TAG (skip migrate)"
		exit 0
	fi
	# Reuse compose invocation (below) with the previous tag, skip migrate
	SKIP_MIGRATE=1
	export TAG
else
	SKIP_MIGRATE=0
	export TAG
fi

# ==============================================================================
# DRY-RUN MODE: print planned steps and exit
# ==============================================================================
if [ "$DRY_RUN" -eq 1 ]; then
	log "[DRY-RUN] Planned steps:"
	log "[DRY-RUN]   1. Fetch .env from taxresearch-env secret"
	log "[DRY-RUN]   2. Read IMAGE_REPO from .env"
	log "[DRY-RUN]   3. Registry login"
	log "[DRY-RUN]   4. Preflight checks"
	log "[DRY-RUN]   5. DB init check (extensions)"
	log "[DRY-RUN]   6. Remember previous tag"
	log "[DRY-RUN]   7. Pull images"
	if [ "$SKIP_MIGRATE" -eq 0 ]; then
		log "[DRY-RUN]   8. Run migrate service"
	fi
	log "[DRY-RUN]   9. Start services (up -d --remove-orphans)"
	log "[DRY-RUN]  10. Verify health (retries up to ${VERIFY_TIMEOUT}s)"
	log "[DRY-RUN]  11. Write tags and prune images"
	exit 0
fi

# ==============================================================================
# STEP 1: Fetch .env from Secret Manager
# ==============================================================================
if [ "${SKIP_SECRETS:-0}" -ne 1 ]; then
	log "Fetching .env from taxresearch-env secret..."
	if ! gcloud secrets versions access latest --secret=taxresearch-env "${PROJECT_ARGS[@]}" > "$ENV_FILE_NEW" 2>/dev/null; then
		logerr "Failed to fetch .env from Secret Manager. Ensure GCP credentials are available."
		exit 1
	fi
	chmod 600 "$ENV_FILE_NEW"
	mv "$ENV_FILE_NEW" "$ENV_FILE"
	log ".env updated from Secret Manager"
else
	log "SKIP_SECRETS=1: using existing .env"
fi

# ==============================================================================
# STEP 2: Read IMAGE_REPO from .env (do NOT source the file)
# ==============================================================================
log "Reading IMAGE_REPO from .env..."
IMAGE_REPO=$(grep "^IMAGE_REPO=" "$ENV_FILE" | cut -d'=' -f2- || true)
if [ -z "$IMAGE_REPO" ]; then
	logerr "IMAGE_REPO not set in .env"
	exit 1
fi
log "Using IMAGE_REPO: ${IMAGE_REPO%%/*}/* (registry only)"

# ==============================================================================
# STEP 3: Registry login
# ==============================================================================
log "Logging in to Artifact Registry..."
REGISTRY_HOST="${IMAGE_REPO%%/*}"
if ! gcloud auth print-access-token 2>/dev/null | \
	podman login -u oauth2accesstoken --password-stdin "$REGISTRY_HOST" >/dev/null 2>&1; then
	logerr "Failed to login to Artifact Registry"
	exit 1
fi
log "Registry login successful"

# ==============================================================================
# STEP 4: Preflight checks
# ==============================================================================
log "Running preflight checks..."
preflight_errors=0

# Check required keys are present and non-empty
for key in DATABASE_URL JWT_SECRET LOG_LEVEL OBJECT_STORE LOCAL_STORE_PATH ADMIN_EMAIL ADMIN_PASSWORD IMAGE_REPO DB_APP_USER DB_NAME; do
	value=$(grep "^${key}=" "$ENV_FILE" | cut -d'=' -f2- || true)
	if [ -z "$value" ]; then
		logerr "Preflight: $key is empty or missing"
		preflight_errors=$((preflight_errors + 1))
	fi
	# Never echo the actual value
done

# Check for obvious misconfigurations
db_url=$(grep "^DATABASE_URL=" "$ENV_FILE" | cut -d'=' -f2- || true)
if [ -z "$db_url" ]; then
	logerr "Preflight: DATABASE_URL missing"
	preflight_errors=$((preflight_errors + 1))
fi
if ! echo "$db_url" | grep -q "sslmode="; then
	logerr "Preflight: DATABASE_URL must contain sslmode="
	preflight_errors=$((preflight_errors + 1))
fi

# Check for placeholder values
if grep -q "change-me" "$ENV_FILE"; then
	logerr "Preflight: .env contains 'change-me' placeholder values"
	preflight_errors=$((preflight_errors + 1))
fi

if [ "$preflight_errors" -gt 0 ]; then
	logerr "Preflight checks failed ($preflight_errors errors)"
	exit 1
fi
log "Preflight checks passed"

# ==============================================================================
# STEP 5: DB init check (extensions must exist)
# ==============================================================================
log "Checking database extensions..."
if ! bash "$DB_INIT_SCRIPT" --check 2>&1 | tee -a "$DEPLOY_LOG"; then
	# First deploy (or a new database): run the one-time setup. It is idempotent.
	log "Database is not set up yet; running the one-time setup (db-init.sh)..."
	if ! bash "$DB_INIT_SCRIPT" 2>&1 | tee -a "$DEPLOY_LOG"; then
		logerr "Database setup failed. See the lines above. Common causes: wrong Cloud SQL private IP, the VM cannot reach it, or the postgres password in Secret Manager is wrong."
		exit 1
	fi
	if ! bash "$DB_INIT_SCRIPT" --check 2>&1 | tee -a "$DEPLOY_LOG"; then
		logerr "Database extensions are still missing after the setup."
		exit 1
	fi
fi
log "Database extensions verified"

# ==============================================================================
# STEP 6: Remember previous tag
# ==============================================================================
if [ -f "$TAG_FILE_CURRENT" ]; then
	PREVIOUS_TAG=$(cat "$TAG_FILE_CURRENT")
	log "Previous tag: $PREVIOUS_TAG"
else
	PREVIOUS_TAG=""
	log "No previous tag (first deploy)"
fi

# ==============================================================================
# STEP 7: Pull images
# ==============================================================================
log "Pulling images (TAG=$TAG, IMAGE_REPO=$IMAGE_REPO)..."
cd "$TAXRESEARCH_DIR"
for service in api worker web; do
	image="${IMAGE_REPO}/${service}:${TAG}"
	log "  Pulling $image..."
	if ! podman pull "$image"; then
		logerr "Failed to pull $image"
		exit 1
	fi
done
log "All images pulled successfully"

# ==============================================================================
# STEP 8: Run migrations (if not rolling back)
# ==============================================================================
if [ "$SKIP_MIGRATE" -eq 0 ]; then
	log "Running database migrations..."
	if ! podman-compose --env-file "$ENV_FILE" -p taxresearch -f "$COMPOSE_FILE" \
		run --rm migrate 2>&1 | tee -a "$DEPLOY_LOG"; then
		logerr "Migrations failed. Cannot proceed. Migrations are forward-only; check the error above."
		exit 1
	fi
	log "Migrations completed successfully"
else
	log "Skipping migrations (rollback mode)"
fi

# ==============================================================================
# STEP 9: Start services
# ==============================================================================
log "Starting services (up -d --remove-orphans)..."
if ! podman-compose --env-file "$ENV_FILE" -p taxresearch -f "$COMPOSE_FILE" \
	up -d --remove-orphans 2>&1 | tee -a "$DEPLOY_LOG"; then
	logerr "Failed to start services"
	exit 1
fi
log "Services started"

# ==============================================================================
# STEP 10: Verify health with retries
# ==============================================================================
log "Verifying services are healthy (up to ${VERIFY_TIMEOUT}s)..."
VERIFY_RETRIES=0
VERIFY_MAX_RETRIES=$((VERIFY_TIMEOUT / 5))
while [ "$VERIFY_RETRIES" -lt "$VERIFY_MAX_RETRIES" ]; do
	if VERIFY_TIMEOUT=5 bash "$VERIFY_SCRIPT" >/dev/null 2>&1; then
		log "Health verification passed"
		VERIFY_SUCCESS=1
		break
	fi
	VERIFY_RETRIES=$((VERIFY_RETRIES + 1))
	sleep 5
done

if [ "${VERIFY_SUCCESS:-0}" -ne 1 ]; then
	logerr "Health verification failed after ${VERIFY_TIMEOUT}s"

	# ==============================================================================
	# STEP 10b: Rollback on failure
	# ==============================================================================
	if [ -n "$PREVIOUS_TAG" ]; then
		log "Attempting rollback to $PREVIOUS_TAG..."
		export TAG="$PREVIOUS_TAG"
		if podman-compose --env-file "$ENV_FILE" -p taxresearch -f "$COMPOSE_FILE" \
			up -d 2>&1 | tee -a "$DEPLOY_LOG"; then
			log "Rollback completed, verifying..."
			VERIFY_RETRIES=0
			VERIFY_SUCCESS=0
			while [ "$VERIFY_RETRIES" -lt "$VERIFY_MAX_RETRIES" ]; do
				if VERIFY_TIMEOUT=5 bash "$VERIFY_SCRIPT" >/dev/null 2>&1; then
					log "Rollback verification passed"
					VERIFY_SUCCESS=1
					break
				fi
				VERIFY_RETRIES=$((VERIFY_RETRIES + 1))
				sleep 5
			done

			if [ "$VERIFY_SUCCESS" -eq 1 ]; then
				logerr "Deploy failed; rollback to $PREVIOUS_TAG was successful"
				exit 1
			else
				logerr "Deploy failed; rollback also failed"
				exit 1
			fi
		else
			logerr "Deploy failed; rollback failed"
			exit 1
		fi
	else
		logerr "Deploy failed; no previous tag to rollback to"
		exit 1
	fi
fi

# ==============================================================================
# STEP 11: Write tags and cleanup
# ==============================================================================
log "Finalizing: writing tags..."
if [ -f "$TAG_FILE_CURRENT" ]; then
	cp "$TAG_FILE_CURRENT" "$TAG_FILE_PREVIOUS"
fi
echo "$TAG" > "$TAG_FILE_CURRENT"
log "Tags written (current=$TAG)"

log "Pruning dangling images..."
podman image prune -f >/dev/null 2>&1 || true

log "Deploy completed successfully: $TAG"
echo "Deployed tag: $TAG"
