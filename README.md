# GST Tax Research Assistant

A research platform for Indian GST law: keyword and citation search, amendment tracking, and linked legal documents. Built as a POC on Podman, then deployed to AWS for production.

**Status:** v0.2 Draft. See [FSD.md](./FSD.md) and [TSD.md](./TSD.md) for requirements and design.

## Repository layout

| Directory | Contents |
|-----------|----------|
| `apps/api/` | FastAPI backend (modular monolith) |
| `apps/worker/` | Ingestion and indexing workers |
| `apps/web/` | Next.js frontend (search, docs, workspace) |
| `packages/legal-core/` | Shared citation parser and legal logic |
| `config/` | YAML configuration (retrieval weights, sources, aliases) |
| `eval/` | Query and fixture sets, evaluation harness |
| `infra/` | Podman Compose (POC) and Terraform (production) |
| `scripts/` | Startup, preflight, verification and code-check scripts |
| `docs/` | Setup guides and runbooks |
| `FSD.md`, `TSD.md` | Functional and technical specifications |

## Quick start: POC

### 1. Set up environment

```bash
cp .env.example .env
# Edit .env and replace 'change-me' values with actual secrets
```

### 2. Start the stack

```bash
# Starts PostgreSQL, MinIO, API, worker, web containers
bash scripts/up.sh

# Verify services are ready
bash scripts/verify.sh
```

Services run at: **Web** http://localhost:3000 · **API** http://localhost:8000

### 3. Create the first admin user

```bash
podman compose -f infra/compose.yaml exec api python -m app.cli create-user --email you@example.com --display-name "Your Name" --role platform_admin

# Check that the audit log hash chain is intact
podman compose -f infra/compose.yaml exec api python -m app.cli verify-audit
```

The CLI asks for a password (at least 12 characters) twice. Set `TAXRESEARCH_PASSWORD` to skip the prompt.

### 4. Dev setup (optional, for local testing)

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements-dev.txt
```

### 5. Code quality

```bash
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m mypy apps/worker apps/api packages/legal-core/src scripts
.venv/Scripts/python -m pytest -q -m "not integration"
```

## Loading documents

The worker loads PDF and HTML documents in three ways. Each load needs a `--source` code from `config/sources.yaml` and a `--doc-type` from `config/authority.yaml` (`notification`, `circular`, `instruction`, `order`, `judgement`, `act`, `rules`, `other`). Metadata options are optional. With enough of them (for example series, number and year for a notification) the document gets its real canonical ID; otherwise it gets a provisional `unk:` ID until classification (M3).

**Watch folder.** Copy a file to `infra/watch/<source_code>/<doc_type>/<file>`, for example `infra/watch/cbic_gst_portal/notification/ct11-2017.pdf`. The worker checks the folder every few seconds. When a file has stopped changing it moves the file to `.done/<yyyymmdd>/` and loads it. A file that cannot be loaded goes to `.failed/` with a `<name>.reason.txt` beside it.

**CLI** (run inside the worker container):

```bash
podman compose -f infra/compose.yaml exec worker python -m worker.cli ingest-url \
  https://www.cbic-gst.gov.in/gst/notifications/ct11-2017.pdf \
  --source cbic_gst_portal --doc-type notification --series CT --number 11 --year 2017

podman compose -f infra/compose.yaml exec worker python -m worker.cli ingest-file \
  /watch/cbic_gst_portal/notification/ct11-2017.pdf \
  --source cbic_gst_portal --doc-type notification --series CT --number 11 --year 2017

podman compose -f infra/compose.yaml exec worker python -m worker.cli job-status <ingestion-job-id>
```

Each command prints the ingestion job id. Fetch-by-URL only accepts `http` and `https` URLs on the hosts listed for the source in `config/sources.yaml`. Downloads are capped at 50 MB and private addresses are refused.

**API** (needs `ingest.submit`; reading needs `ingest.read`):

```bash
curl -X POST http://localhost:8000/v1/platform/ingestion/url \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"source": "cbic_gst_portal", "doc_type": "notification", "url": "https://www.cbic-gst.gov.in/gst/notifications/ct11-2017.pdf", "series": "CT", "number": 11, "year": "2017"}'

curl http://localhost:8000/v1/platform/ingestion/jobs/<ingestion-job-id> -H "Authorization: Bearer $TOKEN"
```

The POST returns `202` with `ingestion_job_id`. File upload through the API is deferred to M3.

## Data rules

- **Public documents only** in the POC: CGST Act, IGST Act, notifications, circulars, SC/HC/GSTAT judgements (1 July 2017 onwards).
- **No sensitive data** in the repo: never commit `.env`, data files, database dumps, or real credentials.
- **Test data** must be synthetic: use realistic but fictional case names, dates, and amounts.
- **Use fixtures** from `eval/fixtures/` rather than copying real documents.

## Deployment

### POC (Podman, local machine)

See _Quick start_ above.

### Production (AWS)

Deferred. See P-1, P-2, P-3, P-4 in TSD section 13.2 (milestones).

## Architecture

- **Database:** PostgreSQL 16 with full-text search (POC), or OpenSearch (production).
- **Object store:** MinIO with S3 API (POC), or Amazon S3 (production).
- **Auth:** Email + password with JWT (POC), or Cognito with TOTP MFA (production).
- **Job queue:** Postgres SELECT...FOR UPDATE (POC), or SQS (production).
- **Web:** Next.js + TypeScript + Tailwind, SSR for reader pages.

See [TSD.md](./TSD.md) section 2 for the full system diagram and section 3 for the technology stack.

## Contributing

- Follow the workflow in [CLAUDE.md](./CLAUDE.md): plan → freeze → code.
- All changes require a plan document reviewed by the team.
- Code review and tests before merge.

## References

- [Functional Specification (FSD)](./FSD.md)
- [Technical Specification (TSD)](./TSD.md)
- [CLAUDE.md](./CLAUDE.md): project workflow

## License and compliance

- Public documents used are from official sources (CBIC, courts, tribunal websites).
- Judgements are from court-issued copies; no reporter headnotes are reproduced without license.
- Code is internal; no open-source license yet.
- DPDP Act 2023 (India data protection): applies to production profile and private uploads (P2).

## Support

Questions about the design or build? See the TSD, FSD, or open an ADR for a design decision.
