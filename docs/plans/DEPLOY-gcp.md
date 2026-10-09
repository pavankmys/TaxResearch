# Deployment to GCP (Compute Engine + Cloud SQL)

**Status: approved by the user on 2026-10-09 (frozen).** Scope changes during coding require stopping and re-planning with the user. Nothing here touches the user's GCP project until the user asks for a specific command to be run.

Refs: `docs/DEBIAN_SETUP.md` (stale, on-prem), `infra/compose.yaml`, `scripts/`, `.github/workflows/ci.yml`, TSD 13.

## Goal

Redeploy the POC to one Compute Engine VM, using the existing Cloud SQL for PostgreSQL, with one click. No manual copying of files, no editing of Compose by hand, no hand-made admin user. Secrets never enter the repository or the chat.

## Decisions (user, 2026-10-09)

| Question | Answer |
| --- | --- |
| Database | Cloud SQL for PostgreSQL, **private IP** in the VM's VPC |
| Deploy trigger | **GitHub Actions button** (build, push, deploy); needs a one-time bootstrap run in Cloud Shell |
| Access | **IAP tunnel only**: no public listener, no domain, no certificates |
| VM runtime | **Debian 13 with rootless Podman** |

## Design

```
GitHub (manual button)      Artifact Registry         Compute Engine VM (Debian 13, Podman, no public port)
  build 3 images   ----->   api / worker / web  --->  deploy.sh: pull, migrate, up, verify, roll back
  push, then IAP SSH        tagged by commit SHA      web 127.0.0.1:3000 -> api -> Cloud SQL (private IP, TLS)
                                                      worker; object store on a persistent disk
You: gcloud compute start-iap-tunnel <vm> 3000 --local-port=3000  ->  http://localhost:3000
```

- **Images are built once in CI**, not on the VM. The worker image carries Tesseract and OCRmyPDF; the VM only pulls.
- **One deploy script on the VM** (`scripts/deploy.sh <tag>`): pull images, run migrations once, start the stack, wait for health, and return to the previous tag if health fails.
- **Secrets** live in GCP Secret Manager and are written to `/opt/taxresearch/.env` (mode 600) by the deploy script, using the VM's own service account. GitHub keeps only identifiers for keyless login (Workload Identity Federation limited to this repository), never a key.
- **Database:** the stack uses Cloud SQL through `DATABASE_URL` alone, with `sslmode=require`. No Postgres container.
- **Object store:** a named volume on the VM's persistent disk (`OBJECT_STORE=local`), shared by the API and the worker. No MinIO. A bucket can replace it later.
- **Access:** the web port is bound to the VM's loopback. `COOKIE_SECURE` stays `true`: Chrome, Edge and Firefox accept secure cookies on `http://localhost`. If login does not stick in the user's browser (for example Safari), the documented fallback is `COOKIE_SECURE=false`, which is acceptable only because the IAP tunnel is already encrypted and nothing is publicly exposed.
- **Restart on reboot:** rootless Podman with lingering enabled for a dedicated `taxresearch` user and the user `podman-restart` service; containers use `restart: always`.

## Assumptions to confirm before freeze
1. The VM can reach the internet for packages and the Artifact Registry (an external IP, or Cloud NAT plus Private Google Access).
2. The user can create IAM bindings and a Workload Identity pool in the project (project owner or equivalent) to run the bootstrap once.
3. The GitHub repository `pavankmys/TaxResearch` hosts the workflow. The deploy workflow is **manual only** (CI minutes are limited); automatic deploy after green CI can be switched on later.
4. The Cloud SQL admin user (default `postgres`) can create extensions (`cloudsqlsuperuser`); the bootstrap asks for its password through a hidden prompt and stores it in Secret Manager.

## Work items

### D1. Make the stack deployable (code and config changes)
1. `infra/compose.gcp.yaml`: api, worker, web; images from the registry by tag; named volumes for the object store and the worker drop folder; a one-shot `migrate` service that runs `alembic upgrade head` before the API starts; no postgres, minio or minio-init; web published on `127.0.0.1:3000` only; `restart: always`.
2. API image: `RUN_MIGRATIONS=false` skips `alembic upgrade head` on start (the `migrate` service does it once). The default stays unchanged for local use.
3. `scripts/wait_for_db.py`: parse `DATABASE_URL` with SQLAlchemy's URL parser so percent-encoded passwords and `?sslmode=` work.
4. API: add `GET /ready` (503 when the database is unreachable). `/health` keeps today's behavior.
5. Worker: a heartbeat file and a container healthcheck.
6. First admin: `python -m app.cli ensure-admin` creates the first `platform_admin` from `ADMIN_EMAIL` and `ADMIN_PASSWORD` (from Secret Manager) only when no admin exists. Idempotent; runs inside the deploy.
7. Environment: one `/opt/taxresearch/.env` for both Compose interpolation and the containers; a preflight for the external-database variant (no `POSTGRES_*`, no MinIO).
8. Database setup once: `infra/gcp/db-init.sql` creates the four extensions (`citext`, `ltree`, `pg_trgm`, `btree_gist`) with the admin role, and an app role with the privileges the migrations need.

### D2. Build and deploy automation
1. `.github/workflows/deploy.yml`: `workflow_dispatch` with an optional tag input. Builds the three images, pushes to Artifact Registry, then runs `deploy.sh` on the VM over IAP SSH. Keyless login by Workload Identity Federation.
2. `infra/gcp/bootstrap.sh`: run **once by the user** in Cloud Shell. Creates the Artifact Registry repository, a deploy service account with minimum roles (Artifact Registry writer, IAP tunnel user, OS Login on the VM), the Workload Identity pool and provider restricted to this repository, the IAP SSH firewall rule, and the Secret Manager entries. It asks for secret values through hidden prompts and never prints them. Idempotent.
3. `infra/gcp/vm-setup.sh`: run once on the VM. Installs Podman and `podman-compose`, creates the `taxresearch` user with lingering, `/opt/taxresearch`, the registry credential helper, and enables `podman-restart`.
4. `scripts/deploy.sh`: as above, logging to a file, non-zero exit on failure.
5. `scripts/verify.sh`: fixed to run on Linux, check `/ready`, the web sign-in page and the worker heartbeat, and exit non-zero on failure.

### D3. Documentation
`docs/DEPLOY_GCP.md`: the one-time setup, the day-to-day commands (open the tunnel, deploy, roll back, logs, backup, restore), and a troubleshooting table. README and HANDOFF point to it. FSD and TSD hosting sections change from Debian/Podman on-prem to GCP.

## Out of scope
Terraform, multiple VMs, high availability, a public domain, Caddy or any TLS termination, WAF/CDN, alerting (Cloud Logging collects container output by default), moving documents to a Cloud Storage bucket, and automatic deploy on push.

## Verification
- On this machine (no container runtime): `ruff`, `mypy`, unit tests for the new Python (URL parsing, `ensure-admin`, `/ready`), `shellcheck` on the scripts if available, YAML parse of the Compose file and workflow.
- **Not verifiable here:** the Compose file, the images, the workflow and the bootstrap against a real project. The first deploy on the VM is the real test, so it is done step by step with the user, and `deploy.sh` rolls back on a failed health check.
- Acceptance on the VM: `scripts/verify.sh` passes; sign in as the first admin through the tunnel; upload a PDF in the console and watch it reach `published`; run the deploy again and confirm it restarts cleanly.

## Review changes / Known gaps
(To be filled in at the end of the work.)

### Review changes and decisions (2026-10-09)
- **Built in two parallel tracks** (code and compose; workflow and scripts) against one contract, then **reviewed and largely rewritten by the main session.** The implementers' own reports said "all lint passed" and "verified"; review found defects that lint cannot see, so the scripts were also exercised against stand-ins for `gcloud`, `podman` and `podman-compose`.
- **Defects found and fixed in review:**
  - Workflow: user input interpolated into a `run:` body (script injection); a broken `--command='…'` quote; a default-tag line that did nothing; no Buildx, so registry caching could not work; files copied to a world-writable `/tmp`.
  - `deploy.sh`: `((n++))` aborts under `set -e` when `n` is 0 (it would have stopped on the first health retry); verify attempts that each waited up to 120 s; an empty `--project=` flag.
  - `bootstrap.sh`: sequential `${var//…/…}` substitutions that rewrote the `DB_NAME=` key itself; the Workload Identity principal built from the project ID instead of the project number; `serviceAccountUser` granted on the wrong account; an invented VM service account when the VM was not found; project-wide grants where narrow ones were planned; the firewall rule on the default network; all errors hidden; no check of the VM's access scopes.
  - `vm-setup.sh`: `apt-key` (absent on Debian 13); hidden apt errors; the `podman-restart` enable ran before the user's service manager was up.
  - `db-init.sql` / `db-init.sh`: psql variables inside `DO $$` blocks and as identifiers (neither works); a Python helper that read its script and its input from the same stdin; the admin password parsed in the wrong format; the application password on a command line.
  - Compose: `depends_on: migrate` re-ran the migration on every `up`; every service received the whole `.env` including the admin password.
  - API image: a failed migration no longer stopped the container (`… || true`).
- **Decision: the database is set up by the first deploy**, not by a manual step (the user wants little DevOps). `deploy.sh` runs the idempotent `db-init.sh` when the check fails. The `postgres` password stays readable by the VM's account; the guide shows how to remove that after the first deploy.
- **The guide was rewritten** to match what the scripts do (secret rotation, first-admin behaviour, the default-branch requirement, VM access scopes).

### Known gaps
- **Nothing has run against a real project, VM, Podman or Cloud SQL.** The psql in `db-init.sql` (`\getenv` needs psql 15+, which the postgres:16 image has), `podman-compose` behaviour with `run --rm` and named volumes under rootless Podman, Workload Identity Federation, and OS Login SSH are the likeliest places for a first-run surprise.
- The worker heartbeat proves the process is alive, not that its job loop is making progress.
- No monitoring or alerting; one VM; no automatic deploy; no image vulnerability scanning.
- `COOKIE_SECURE` stays on; Safari may refuse the cookie over `http://localhost`.
