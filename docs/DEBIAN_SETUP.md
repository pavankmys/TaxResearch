# TaxResearch POC Setup on Debian 13

Step-by-step guide to set up the TaxResearch POC on a fresh Debian 13 machine with rootless Podman.

## System requirements

- Debian 13 machine with at least 16 GB RAM and 100–150 GB disk
- Network access (for pulling container images)
- User with sudo access

## Step 1: Install Podman and dependencies

```bash
sudo apt update
sudo apt install -y podman podman-compose
```

Verify installation:

```bash
podman --version
podman-compose --version
```

Both should show version 4.x or later. Verify that `podman compose` works (without the dash):

```bash
podman compose --version
```

## Step 2: Configure rootless Podman

On Debian, rootless Podman requires subuid and subgid ranges.

```bash
# Add subuid and subgid ranges for your user (replace 'user' with your username)
sudo usermod --add-subuids 100000-165535 user
sudo usermod --add-subgids 100000-165535 user
```

Enable lingering to allow containers to survive logout:

```bash
loginctl enable-linger
```

Verify your user has the ranges:

```bash
cat /etc/subuid | grep $USER
cat /etc/subgid | grep $USER
```

Both should show an entry. If not, add them manually to `/etc/subuid` and `/etc/subgid`.

## Step 3: Clone the repository

```bash
cd /path/to/projects
git clone <repository-url>
cd TaxResearch
```

## Step 4: Set up environment

Copy the environment template and set values:

```bash
cp .env.example .env
```

Edit `.env` and replace all `change-me` values with actual values. For development/testing, you can generate secure random values:

```bash
# Generate a random password for Postgres
openssl rand -base64 24

# Generate a random JWT secret (must be at least 32 characters)
openssl rand -base64 32
```

Example `.env` values:

```
POSTGRES_USER=taxresearch
POSTGRES_PASSWORD=<generated-password>
POSTGRES_DB=taxresearch
DATABASE_URL=postgresql://taxresearch:<password>@localhost:5432/taxresearch

S3_ACCESS_KEY=<generated-key>
S3_SECRET_KEY=<generated-secret>
S3_BUCKET=taxresearch

JWT_SECRET=<generated-secret-min-32-chars>
LOG_LEVEL=INFO
```

Verify `.env` is not committed:

```bash
grep .env .gitignore  # Should output: .env
```

## Step 5: Start the stack

Run preflight checks and start containers:

```bash
bash scripts/up.sh
```

This will:
1. Verify `.env` is configured correctly
2. Build container images
3. Start services in the background: PostgreSQL, MinIO, API, worker, web

Check logs while services start:

```bash
podman compose -f infra/compose.yaml logs -f
```

Wait for all services to report as "ready". The API container will run migrations on first start.

## Step 6: Verify the deployment

Once services are running, verify they are healthy:

```bash
bash scripts/verify.sh
```

This script:
- Waits up to 2 minutes for the API to respond
- Checks the web app (should return HTTP 200)
- Runs the OCR smoke test (requires tesseract; can be skipped if not installed)
- Prints expected output and endpoints

Expected output:

```
✓ Database is ready at localhost:5432/taxresearch
✓ API is responding
API health status:
{"status": "ok", "version": "0.1.0"}

✓ Web service is responding (HTTP 200)
✓ Verification complete!

Next steps:
  - Web app: http://127.0.0.1:3000
  - API: http://127.0.0.1:8000
```

## Step 7: Access the services

Once verification passes:

| Service | URL | Notes |
|---------|-----|-------|
| Web app | http://127.0.0.1:3000 | Search, docs, workspace |
| API | http://127.0.0.1:8000 | REST endpoints |
| API docs | http://127.0.0.1:8000/docs | Swagger UI |
| MinIO console | http://127.0.0.1:9001 | S3 object storage browser |

## Common issues

### Issue: `podman: unqualified-search-registries`

**Cause:** Podman cannot find images without a full registry address.

**Solution:** Edit `/etc/containers/registries.conf` and ensure docker.io is in the search registries, or use fully qualified image names (e.g., `docker.io/library/postgres:16`).

### Issue: Port already in use

**Cause:** Another service is using port 8000, 3000, or 5432.

**Solution:**
```bash
# Find what's using the port (example: 8000)
sudo lsof -i :8000

# Or: stop the conflicting service
sudo systemctl stop <service-name>
```

### Issue: Volume permission denied

**Cause:** Rootless Podman containers run as a non-root user inside the container, which may not match your local user ID.

**Solution:** Ensure the `watch` folder is writable:
```bash
mkdir -p ./watch
chmod 777 ./watch
```

Or use `Z` option in volume mounts (already set in compose.yaml): `./watch:/watch:Z`

### Issue: No tesseract found

**Cause:** OCR smoke test requires tesseract-ocr.

**Solution:** Install tesseract (optional; OCR tests will be skipped):
```bash
sudo apt install tesseract-ocr tesseract-ocr-eng ghostscript qpdf
```

### Issue: Database migration fails

**Cause:** Alembic version mismatch or schema lock.

**Solution:**
```bash
# View API logs
podman compose -f infra/compose.yaml logs api

# Manually run migrations (if needed)
podman compose -f infra/compose.yaml exec api \
  alembic upgrade head
```

## Stopping and resetting

### Stop services

```bash
podman compose -f infra/compose.yaml down
```

Services will stop but data persists in volumes.

### Reset volumes (WARNING: deletes all data)

```bash
podman compose -f infra/compose.yaml down -v
```

This deletes PostgreSQL and MinIO data. The next `up.sh` will recreate empty databases.

### View logs

```bash
# All services
podman compose -f infra/compose.yaml logs -f

# Specific service
podman compose -f infra/compose.yaml logs -f api
podman compose -f infra/compose.yaml logs -f worker
```

## Next steps

- Import sample documents into the `watch/` folder for ingestion
- Check the API Swagger UI for available endpoints
- See [FSD.md](../FSD.md) and [TSD.md](../TSD.md) for architecture and design

## Troubleshooting

For more help:
- Check [TSD.md](../TSD.md) section 2.4 (POC profile notes)
- Review container logs: `podman compose -f infra/compose.yaml logs <service>`
- Check Podman documentation: https://docs.podman.io/

## Auto-start at boot (future enhancement)

To automatically start the stack on boot, use systemd Quadlet:

```bash
# Create Quadlet units (requires Podman 4.4+)
sudo podman generate systemd --new --files \
  -f $(pwd)/infra/compose.yaml
```

This is a future enhancement and not required for the POC.
