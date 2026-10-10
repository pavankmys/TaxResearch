# Hand-off: where the build stands

Last updated: 2026-10-10.
Milestones M0 through M5 (including M4c Consolidation and M5 Search & Retrieval Slices 1, 2, and 3) are fully implemented, verified, and tested. Deployment to GCP is deferred.

---

## Workflow rules (from CLAUDE.md and the user)

- **Plan, freeze, code.** Write a plan in `docs/plans/`. Get explicit user approval and mark the plan file "approved by the user on <date> (frozen)". Implementers check that line before they code. If scope has to change, stop and re-plan with the user.
- **Never push without explicit approval.** Never execute `git push` or publish actions to remote repositories without explicit approval from the user. Commit locally only.
- **Never go out of scope to fix.** Report discovered out-of-scope bugs clearly rather than fixing them silently.
- **Strict data privacy & synthetic fixtures.** Zero hardcoded secrets, mask all PII / financial identifiers, and use synthetic test data only.
- **Cost-aware delegation & CI limits.** CI runs on pull requests and pushes to `main`. Keep commits organized locally.

---

## Milestones Summary

| Milestone | Status | Plan | Details / Main Commits |
| --- | --- | --- | --- |
| **M0 Foundations** | Done | (audit only) | Container setup, base configs (`ac54abd`, `7c46477`). |
| **M1 Core data & auth** | Done | `docs/plans/M1-core-data-and-auth.md` | Tenant/user auth, sessions, RBAC, audit logging (`6d46afd` to `0a9628e`). |
| **M2 Fetch, parse, store** | Done | `docs/plans/M2-fetch-parse-store.md` | Worker pipeline, PDF parsing, OCR, checksum dedup (`70dc8bc`, `36a95c4`, `195fe19`). |
| **M3a Backend: structure & metadata** | Done | `docs/plans/M3-structure-and-metadata.md` | Segmentation, metadata extraction, document publishing (`529cc72`, `bdb86f2`). |
| **M3b Reviewer console** | Done | same | Next.js reviewer console, queue management, task views (`b24bd7d`, `84363df`). |
| **M4a Baseline Acts & Rules** | Done | `docs/plans/M4-amendment-engine-and-baseline.md` | Instrument loader, baseline provision trees, verification API & UI. |
| **M4b Amendment detector** | Done | same | Lark amendment grammar, proposal generation, review tasks. |
| **M4c Apply, consolidate, view** | Done | same | Bi-temporal provision versions, consolidation stage, point-in-time APIs (`/v1/provisions/{id}`, `/timeline`, `/diff`), reviewer diff pane (`f9ab66d`). |
| **M5 Search & retrieval** | **Done** | `docs/plans/M5-search-and-retrieval.md` | **Slice 1, 2 & 3 complete**: legal structure chunking, bi-temporal `chunks` table, PostgreSQL FTS ranking engine, query expansion (`synonyms.yaml`), citation resolver (`/v1/resolve`), search APIs (`/v1/search`, `/v1/provisions/{id}/linked`), search console UI (`/search`), citation banner, filter sidebar, grouped results, provision linked panel (`c1ddb2c`, `a988132`). |
| **M6 Citations & Links Graph** | Ready to plan | TSD 13.2 | Next upcoming milestone. |

---

## What Exists in the Codebase

### 1. Database & Migrations
- Migrations `0001` to `0007`: covers core documents, provisions, bi-temporal `provision_versions`, `chunks` (FTS tsvector index), `links` (mentions, amending relations, issued_under, clarifies, interprets), `review_tasks`, `audit_log`, and dashboard views.

### 2. API (`apps/api`)
- **Auth & RBAC**: `/v1/auth/login`, `/v1/auth/logout`, `/v1/me`, `search.read`, `provisions.read`, `review.decide`.
- **Provisions**: `/v1/provisions/{id}` (as-on point-in-time lookup), `/v1/provisions/{id}/timeline`, `/v1/provisions/{id}/diff`.
- **Search & Retrieval**:
  - `GET /v1/resolve`: Citation string parser and resolver (provisions, notifications, circulars) with confidence and alternatives.
  - `GET /v1/search`: Point-in-time full-text search with synonym query expansion, authority/court/state/date filtering, multi-factor ranking, and snippet highlights.
  - `GET /v1/provisions/{id}/linked`: Returns amending instruments, issued-under notifications, clarifying circulars, interpreting judgements, and mentions.
- **Documents & Review**: `/v1/platform/documents`, `/v1/review/tasks`, `/v1/ingest/jobs`.
- **CLI**: `python -m app.cli create-user | verify-audit`.

### 3. Worker (`apps/worker`)
- Pipeline stages:
  1. `acquire`: fetch, dedup, URL/upload.
  2. `parse`: dual engine (PyMuPDF / pdfplumber), OCR fallback.
  3. `classify`: document categorization.
  4. `segment`: Lark numbering grammar, block hierarchy.
  5. `extract_meta`: document metadata extraction.
  6. `apply_metadata`: attach metadata to documents.
  7. `publish`: document publishing, baseline provisions extraction.
  8. `consolidate` (`ingest.consolidate`): applies approved amendments to `provision_versions`.
  9. `index_chunks` (`ingest.index`): generates weighted legal structure chunks (`leaf_provision`, `section_summary`, `numbered_para`, `merged_circular`, `judgement_section`) into `chunks` table.
  10. `mentions`: scans document blocks for provision citations and registers `mentions` in `links`.
- CLI commands: `ingest-file`, `ingest-url`, `job-status`, `index-document`, `index-provisions`.

### 4. Web Console (`apps/web` - Next.js 15, React 19)
- **Search Console (`/search`)**:
  - Search bar with live debounced citation detection prompt and jump link (`search-bar.tsx`).
  - As-on date picker (defaulting to today in IST) for point-in-time legal corpus querying.
  - Query expansion chips for synonym terms (`ITC` → `Input Tax Credit`).
  - Filter sidebar with facet counts (`search-filters.tsx`).
  - Grouped results view with authority badges, court/state tags, sanitized `<mark>` highlights, and expandable passage counts (`search-results.tsx`).
  - Next.js API proxy route `/api/resolve` for client-side citation detection.
- **Provision Detail & Linked Panel (`/baseline/[code]`)**:
  - Chronological version timeline (`provision-timeline.tsx`).
  - Linked resources panel (`provision-linked.tsx`) showing amending instruments, clarifying circulars, issued-under notifications, and citations.
- **Review Queue (`/queue`)**:
  - Document and amendment review views, confidence badges, dry-run diff pane (`amendment-section.tsx`).
- **Dashboard & Documents**:
  - Ingestion metrics, alerts banner, document list and inspection.

---

## Test & Verification Health

All checks pass cleanly across the repository:
- **Python Unit & Non-Integration Tests**: `1,017 passed`, 1 skipped (tesseract OCR fixture).
  ```bash
  .venv\Scripts\pytest -q -m "not integration"
  ```
- **Type Checking (Python)**: `mypy` strict clean across 92 source files.
  ```bash
  .venv\Scripts\mypy
  ```
- **Linter & Formatter (Python)**: `ruff check .` (0 errors) and `ruff format --check .` (207 files formatted).
  ```bash
  .venv\Scripts\ruff check .
  .venv\Scripts\ruff format --check .
  ```
- **Web Unit & Component Tests (Vitest)**: `145 passed` across 29 test files.
  ```bash
  cd apps/web && npm test
  ```
- **TypeScript Type Checking (Web)**: `tsc --noEmit` passed cleanly (0 errors).
  ```bash
  cd apps/web && npm run typecheck
  ```
- **Linter (Web)**: ESLint passed cleanly.
  ```bash
  cd apps/web && npm run lint
  ```

---

## Where the GCP Deployment Stands (Deferred)

The user has explicitly deferred deployment to Google Cloud Platform until local milestones are completed.

When ready to proceed with deployment:
1. **Minor Fix**: Update `infra/gcp/vm-setup.sh` step 6 to run from `/` or with `runuser -l` to avoid false-positive error reporting.
2. **VM Pre-Flight**:
   - Verify Cloud SQL connectivity on port 5432 from `tx-research-vm`.
   - Verify Secret Manager access (`taxresearch-env`, `taxresearch-db-admin`).
3. **Deploy Workflow**:
   - Trigger the GitHub Actions "Deploy to GCP" workflow manually.
   - Establish IAP tunnel (`gcloud compute start-iap-tunnel`) and verify `/ready` returns 200.

---

## Recommended Next Steps

1. **Milestone M6 (Citations & Graph Navigation)**:
   - Formulate plan for bidirectional citation navigation, circular-to-provision graph, and judicial treatment classification.
   - Plan, freeze, and get user alignment before coding.
