#!/usr/bin/env bash
# One-time bootstrap, run by the project owner in Cloud Shell (safe to run again).
#
# Creates what the GitHub deploy workflow and the VM need: Artifact Registry repository, deploy
# service account, keyless GitHub login (Workload Identity Federation, limited to one repository),
# IAM bindings, the IAP SSH firewall rule, and the two Secret Manager secrets.
# Secret values are typed at hidden prompts or generated here. They are never printed, never
# written to disk and never put on a command line.
#
# It only adds things. It deletes nothing.

set -euo pipefail

info() { printf '%s\n' "$*"; }
ok() { printf '  ok: %s\n' "$*"; }
die() {
	printf 'ERROR: %s\n' "$*" >&2
	exit 1
}

# ask VAR "Prompt" "default" "regex that the answer must match" "what is allowed"
ask() {
	local var="$1" prompt="$2" default="$3" regex="$4" allowed="$5" answer
	while true; do
		read -r -p "$prompt [$default]: " answer
		answer="${answer:-$default}"
		if [[ "$answer" =~ $regex ]]; then
			printf -v "$var" '%s' "$answer"
			return 0
		fi
		info "  Not accepted. Allowed: $allowed"
	done
}

command -v gcloud >/dev/null 2>&1 || die "gcloud was not found. Run this in Cloud Shell."
command -v openssl >/dev/null 2>&1 || die "openssl was not found."

PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
[ -n "$PROJECT" ] || die "No project is set. Run: gcloud config set project YOUR_PROJECT_ID"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
[ -n "$PROJECT_NUMBER" ] || die "Could not read the project number for $PROJECT."

info "TaxResearch GCP bootstrap for project: $PROJECT"
info "Press Enter to accept the value in brackets."
info ""

ask GCP_REGION "Region" "asia-southeast2" '^[a-z]+-[a-z]+[0-9]+$' "a region such as asia-southeast2"
ask GCP_ZONE "Zone of the VM" "${GCP_REGION}-a" '^[a-z]+-[a-z]+[0-9]+-[a-z]$' "a zone such as asia-southeast2-a"
ask GCP_VM "VM name" "taxresearch" '^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$' "lower-case letters, digits and dashes"
ask GITHUB_REPO "GitHub repository (owner/name)" "pavankmys/TaxResearch" '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$' "owner/name"
ask AR_REPO "Artifact Registry repository" "taxresearch" '^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$' "lower-case letters, digits and dashes"
ask CLOUDSQL_IP "Cloud SQL private IP address" "" '^([0-9]{1,3}\.){3}[0-9]{1,3}$' "an IPv4 address such as 10.0.0.5"
ask DB_NAME "Database name" "taxresearch" '^[a-z][a-z0-9_]{0,62}$' "lower-case letters, digits and underscores"
ask DB_APP_USER "Application database role" "taxresearch_app" '^[a-z][a-z0-9_]{0,62}$' "lower-case letters, digits and underscores"
ask ADMIN_EMAIL "Email of the first admin user" "" '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$' "an email address"

DEPLOY_SA_NAME="taxresearch-deploy"
DEPLOY_SA="${DEPLOY_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
WIF_POOL="github-pool"
WIF_PROVIDER="github-provider"
IMAGE_REPO="${GCP_REGION}-docker.pkg.dev/${PROJECT}/${AR_REPO}"

info ""
info "Step 1/7  Reading the VM"
VM_INFO="$(gcloud compute instances describe "$GCP_VM" --zone "$GCP_ZONE" --project "$PROJECT" \
	--format='value(serviceAccounts[0].email,networkInterfaces[0].network.basename(),serviceAccounts[0].scopes.join(","))')" ||
	die "The VM '$GCP_VM' was not found in zone $GCP_ZONE. Create it first, then run this again."
IFS=$'\t' read -r VM_SA VM_NETWORK VM_SCOPES <<<"$VM_INFO"
[ -n "$VM_SA" ] || die "The VM has no service account. Attach one (the default compute account is fine) and run again."
ok "VM service account: $VM_SA"
ok "VM network: $VM_NETWORK"
if [[ "$VM_SCOPES" != *"cloud-platform"* ]]; then
	info ""
	info "  WARNING: the VM was created with limited API access scopes. It will not be able to"
	info "  read Secret Manager or Artifact Registry until the scope is widened. Fix, once:"
	info "    gcloud compute instances stop $GCP_VM --zone $GCP_ZONE --project $PROJECT"
	info "    gcloud compute instances set-service-account $GCP_VM --zone $GCP_ZONE --project $PROJECT \\"
	info "      --service-account $VM_SA --scopes cloud-platform"
	info "    gcloud compute instances start $GCP_VM --zone $GCP_ZONE --project $PROJECT"
	info ""
fi

info ""
info "Step 2/7  Enabling APIs"
gcloud services enable artifactregistry.googleapis.com iamcredentials.googleapis.com \
	iap.googleapis.com secretmanager.googleapis.com compute.googleapis.com \
	sts.googleapis.com oslogin.googleapis.com cloudresourcemanager.googleapis.com \
	--project "$PROJECT" --quiet
ok "APIs enabled"

info ""
info "Step 3/7  Artifact Registry and the deploy service account"
if gcloud artifacts repositories describe "$AR_REPO" --location "$GCP_REGION" --project "$PROJECT" >/dev/null 2>&1; then
	ok "Repository exists: $AR_REPO"
else
	gcloud artifacts repositories create "$AR_REPO" --repository-format docker \
		--location "$GCP_REGION" --project "$PROJECT" --quiet
	ok "Repository created: $AR_REPO"
fi
if gcloud iam service-accounts describe "$DEPLOY_SA" --project "$PROJECT" >/dev/null 2>&1; then
	ok "Service account exists: $DEPLOY_SA"
else
	gcloud iam service-accounts create "$DEPLOY_SA_NAME" \
		--display-name "TaxResearch deploy (GitHub Actions)" --project "$PROJECT" --quiet
	ok "Service account created: $DEPLOY_SA"
fi

info ""
info "Step 4/7  Keyless GitHub login (Workload Identity Federation)"
if gcloud iam workload-identity-pools describe "$WIF_POOL" --location global --project "$PROJECT" >/dev/null 2>&1; then
	ok "Pool exists: $WIF_POOL"
else
	gcloud iam workload-identity-pools create "$WIF_POOL" --location global \
		--display-name "GitHub Actions" --project "$PROJECT" --quiet
	ok "Pool created: $WIF_POOL"
fi
if gcloud iam workload-identity-pools providers describe "$WIF_PROVIDER" --location global \
	--workload-identity-pool "$WIF_POOL" --project "$PROJECT" >/dev/null 2>&1; then
	ok "Provider exists: $WIF_PROVIDER"
else
	gcloud iam workload-identity-pools providers create-oidc "$WIF_PROVIDER" --location global \
		--workload-identity-pool "$WIF_POOL" --display-name "GitHub Actions" \
		--issuer-uri "https://token.actions.githubusercontent.com" \
		--attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository" \
		--attribute-condition "assertion.repository == '${GITHUB_REPO}'" \
		--project "$PROJECT" --quiet
	ok "Provider created, limited to repository $GITHUB_REPO"
fi
# The principal uses the project NUMBER, not the project ID.
PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}/attribute.repository/${GITHUB_REPO}"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" \
	--role roles/iam.workloadIdentityUser --member "$PRINCIPAL" --project "$PROJECT" --quiet >/dev/null
ok "Repository $GITHUB_REPO may act as $DEPLOY_SA_NAME"

info ""
info "Step 5/7  Permissions (each one as narrow as possible)"
gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" --location "$GCP_REGION" \
	--member "serviceAccount:${DEPLOY_SA}" --role roles/artifactregistry.writer \
	--project "$PROJECT" --quiet >/dev/null
ok "deploy account: push images to $AR_REPO"
gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" --location "$GCP_REGION" \
	--member "serviceAccount:${VM_SA}" --role roles/artifactregistry.reader \
	--project "$PROJECT" --quiet >/dev/null
ok "VM: pull images from $AR_REPO"
gcloud compute instances add-iam-policy-binding "$GCP_VM" --zone "$GCP_ZONE" \
	--member "serviceAccount:${DEPLOY_SA}" --role roles/compute.osAdminLogin \
	--project "$PROJECT" --quiet >/dev/null
ok "deploy account: log in to $GCP_VM"
gcloud iam service-accounts add-iam-policy-binding "$VM_SA" \
	--member "serviceAccount:${DEPLOY_SA}" --role roles/iam.serviceAccountUser \
	--project "$PROJECT" --quiet >/dev/null
ok "deploy account: use the VM's service account for SSH"
gcloud projects add-iam-policy-binding "$PROJECT" \
	--member "serviceAccount:${DEPLOY_SA}" --role roles/iap.tunnelResourceAccessor \
	--condition=None --quiet >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT" \
	--member "serviceAccount:${DEPLOY_SA}" --role roles/compute.viewer \
	--condition=None --quiet >/dev/null
ok "deploy account: open the IAP tunnel and read VM details"

info ""
info "Step 6/7  Firewall rule for IAP SSH"
if gcloud compute firewall-rules describe allow-iap-ssh-taxresearch --project "$PROJECT" >/dev/null 2>&1; then
	ok "Firewall rule exists: allow-iap-ssh-taxresearch"
else
	gcloud compute firewall-rules create allow-iap-ssh-taxresearch --network "$VM_NETWORK" \
		--allow tcp:22 --source-ranges 35.235.240.0/20 --target-tags taxresearch \
		--project "$PROJECT" --quiet >/dev/null
	ok "Firewall rule created (only Google's IAP range can reach port 22)"
fi
gcloud compute instances add-tags "$GCP_VM" --tags taxresearch --zone "$GCP_ZONE" \
	--project "$PROJECT" --quiet >/dev/null
ok "VM tagged: taxresearch"

info ""
info "Step 7/7  Secrets (typed here, stored in Secret Manager, never shown)"

ADMIN_PASSWORD=""
ADMIN_PASSWORD_CONFIRM=""
while true; do
	read -r -s -p "Password for the first admin user (12+ characters; letters, digits, and @ % + = : , . / _ -): " ADMIN_PASSWORD
	echo
	if ! [[ "$ADMIN_PASSWORD" =~ ^[A-Za-z0-9@%+=:,./_-]{12,128}$ ]]; then
		info "  Not accepted: use 12 to 128 of: letters, digits and @ % + = : , . / _ -"
		continue
	fi
	read -r -s -p "Type it again: " ADMIN_PASSWORD_CONFIRM
	echo
	if [ "$ADMIN_PASSWORD" != "$ADMIN_PASSWORD_CONFIRM" ]; then
		info "  The two entries differ."
		continue
	fi
	break
done

SQL_ADMIN_PASSWORD=""
while true; do
	read -r -s -p "Password of the Cloud SQL 'postgres' user: " SQL_ADMIN_PASSWORD
	echo
	if [ -z "$SQL_ADMIN_PASSWORD" ]; then
		info "  It cannot be empty."
		continue
	fi
	read -r -s -p "Type it again: " SQL_ADMIN_PASSWORD_CONFIRM
	echo
	if [ "$SQL_ADMIN_PASSWORD" != "$SQL_ADMIN_PASSWORD_CONFIRM" ]; then
		info "  The two entries differ."
		continue
	fi
	break
done

JWT_SECRET="$(openssl rand -hex 32)"
DB_APP_PASSWORD="$(openssl rand -hex 24)"

# put_secret NAME: stores stdin as a new version, creating the secret the first time.
put_secret() {
	local name="$1" answer
	if gcloud secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1; then
		read -r -p "Secret '$name' exists. Add a new version? (y/N): " answer </dev/tty
		if [[ "$answer" =~ ^[Yy]$ ]]; then
			gcloud secrets versions add "$name" --data-file=- --project "$PROJECT" --quiet >/dev/null
			ok "new version added: $name"
		else
			cat >/dev/null
			ok "left unchanged: $name"
		fi
	else
		gcloud secrets create "$name" --data-file=- --replication-policy automatic \
			--project "$PROJECT" --quiet >/dev/null
		ok "created: $name"
	fi
}

# The .env text is built with printf so that no character in a value is treated specially.
{
	printf 'DATABASE_URL=postgresql://%s:%s@%s:5432/%s?sslmode=require\n' \
		"$DB_APP_USER" "$DB_APP_PASSWORD" "$CLOUDSQL_IP" "$DB_NAME"
	printf 'JWT_SECRET=%s\n' "$JWT_SECRET"
	printf 'LOG_LEVEL=info\n'
	printf 'OBJECT_STORE=local\n'
	printf 'LOCAL_STORE_PATH=/data\n'
	printf 'ADMIN_EMAIL=%s\n' "$ADMIN_EMAIL"
	printf 'ADMIN_PASSWORD=%s\n' "$ADMIN_PASSWORD"
	printf 'ADMIN_DISPLAY_NAME=Administrator\n'
	printf 'COOKIE_SECURE=true\n'
	printf 'IMAGE_REPO=%s\n' "$IMAGE_REPO"
	printf 'DB_APP_USER=%s\n' "$DB_APP_USER"
	printf 'DB_NAME=%s\n' "$DB_NAME"
} | put_secret taxresearch-env

printf '%s' "$SQL_ADMIN_PASSWORD" | put_secret taxresearch-db-admin

for secret in taxresearch-env taxresearch-db-admin; do
	gcloud secrets add-iam-policy-binding "$secret" --member "serviceAccount:${VM_SA}" \
		--role roles/secretmanager.secretAccessor --project "$PROJECT" --quiet >/dev/null
done
ok "VM may read the two secrets (and nothing else in Secret Manager)"

unset ADMIN_PASSWORD ADMIN_PASSWORD_CONFIRM SQL_ADMIN_PASSWORD SQL_ADMIN_PASSWORD_CONFIRM
unset JWT_SECRET DB_APP_PASSWORD

cat <<EOF

============================================================================
1. In GitHub: Settings > Secrets and variables > Actions > Variables tab.
   Add these seven repository variables (none of them is secret):

   GCP_PROJECT       = ${PROJECT}
   GCP_REGION        = ${GCP_REGION}
   GCP_ZONE          = ${GCP_ZONE}
   GCP_VM            = ${GCP_VM}
   GCP_WIF_PROVIDER  = projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}/providers/${WIF_PROVIDER}
   GCP_DEPLOY_SA     = ${DEPLOY_SA}
   AR_REPO           = ${AR_REPO}

2. Prepare the VM once. From the folder that holds this repository in Cloud Shell:

   gcloud compute scp infra/gcp/vm-setup.sh ${GCP_VM}:~ --zone ${GCP_ZONE} --project ${PROJECT} --tunnel-through-iap
   gcloud compute ssh ${GCP_VM} --zone ${GCP_ZONE} --project ${PROJECT} --tunnel-through-iap --command "sudo bash ~/vm-setup.sh"

3. In GitHub: Actions > "Deploy to GCP" > Run workflow.
   The first run also prepares the database (extensions and the application role).
============================================================================
EOF
