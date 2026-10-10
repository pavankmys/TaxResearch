# TaxResearch Project Task & Milestone Tracker

Last updated: 2026-10-10

---

## 🎯 Current Milestone: M5 (Search and Retrieval)

### Slice 1: Chunking, Indexing Pipeline & Mention Indexer (Worker & Core) - Completed ✅
- [x] **Database & Schema**:
  - [x] Added `chunks` table mapping in `apps/worker/worker/db.py` matching migration `0005_legal_structure.py`.
  - [x] Added `insert_chunks` helper computing weighted PostgreSQL `tsvector` (Headings: Weight A, Body: Weight B).
- [x] **Chunk Generator (`apps/worker/worker/ingest/chunking.py`)**:
  - [x] Legal structure chunking per TSD 6.2 (leaf provisions, notifications by numbered para, circulars merged <80 tokens, judgements by section label).
  - [x] Heading paths (`format_provision_heading_path`) and token counting.
- [x] **Worker Indexing Stage (`apps/worker/worker/ingest/index_chunks.py`)**:
  - [x] Added `INDEX_QUEUE = "ingest.index"` in `apps/worker/worker/ingest/queues.py`.
  - [x] Registered `INDEX_QUEUE` handler in `apps/worker/worker/__main__.py`.
  - [x] Auto-enqueued indexing on document publish (`publish.py`) and provision consolidation (`consolidate.py`).
  - [x] Added CLI commands in `apps/worker/worker/cli.py` (`index-document`, `index-provisions`).
- [x] **Mention Indexer (`apps/worker/worker/ingest/mentions.py`)**:
  - [x] Scans published document blocks for provision citations.
  - [x] Resolves targets to `provisions.id` and records `mentions` links in `links` table.
- [x] **Unit Tests & Verification**:
  - [x] `apps/worker/tests/test_chunking.py` (6/6 tests passing).
  - [x] `apps/worker/tests/test_index_chunks.py` (6/6 tests passing).
  - [x] `apps/worker/tests/test_mentions.py` (4/4 tests passing).
  - [x] `mypy` clean across 87 source files.
  - [x] `ruff check .` and `ruff format --check .` clean (197 files formatted).

---

### Slice 2: Citation Resolver, Search Ranking Engine & REST APIs (API & Core) - Completed ✅
- [x] **Citation Resolver (`GET /v1/resolve`)**:
  - [x] Extend Lark/regex parser in `packages/legal-core/src/legal_core/citations.py` for provision, notification, and circular citations.
  - [x] Build `apps/api/app/routers/resolve.py` returning target entity with confidence and alternatives.
- [x] **Query Expansion Engine (`apps/api/app/modules/search/expansion.py`)**:
  - [x] Load `config/synonyms.yaml` and expand acronyms (ITC, RCM, etc.) with lower weight.
  - [x] Return `expanded_terms` in response.
- [x] **Search Engine & Ranking (`apps/api/app/modules/search/engine.py`)**:
  - [x] PostgreSQL FTS with `websearch_to_tsquery('english', :query)`.
  - [x] Point-in-time `as_on` predicate for provisions and documents.
  - [x] Authority, jurisdiction, recency, and status ranking weights from `config/retrieval.yaml`.
  - [x] Result deduplication (best chunk + child passage count) and `ts_headline` snippets.
  - [x] Keyset/cursor pagination with exact totals (no 500-result cap).
- [x] **Search REST APIs (`apps/api/app/routers/search.py`)**:
  - [x] `GET /v1/search` endpoint.
  - [x] `GET /v1/provisions/{id}/linked` endpoint.
  - [x] Add `"search.read"` permission to `_ANY_USER` in `apps/api/app/auth/permissions.py`.
- [x] **Unit Tests & Verification**:
  - [x] Citation resolution test suite (`test_resolve_api.py`, `test_citations.py`).
  - [x] Search query tests (`test_search_expansion.py`, `test_search_engine.py`, `test_search_api.py`, `test_permissions.py`).
  - [x] Linked provisions API tests (`test_search_api.py`).
  - [x] 1,017 unit tests passing across repo, `mypy` strict clean (92 files), `ruff` clean (207 files formatted).

---

### Slice 3: Search Console UI (Next.js Frontend) - Active ⏳
- [ ] **API Client**:
  - [ ] Export OpenAPI schema and regenerate TypeScript definitions (`apps/web/lib/api-client/schema.d.ts`).
- [ ] **Search UI Components (`apps/web`)**:
  - [ ] Search bar with real-time citation detection prompt.
  - [ ] Point-in-time `as_on` date picker (defaulting to today in IST).
  - [ ] Query expansion chips ("Also searched: Input Tax Credit").
  - [ ] Filter sidebar (document types, authorities, date ranges, topics).
  - [ ] Grouped results cards with binding/authority badges and expandable child passages.
- [ ] **Provision Linked Resources Drawer**:
  - [ ] Display linked amending instruments, circulars, judgements, and mentions on provision views.
- [ ] **Unit Tests & Verification**:
  - [ ] Vitest component tests in `apps/web`.
  - [ ] TypeScript typecheck and ESLint pass.

---

## 🏁 Completed Milestones
- [x] **M4c (Apply, Consolidate, View)**:
  - [x] Slice 1: Database schema, dry-run diff, review task decisions for amendments, `ingest.consolidate` worker stage.
  - [x] Slice 2: Point-in-time REST APIs (`/v1/provisions/{id}`, `/timeline`, `/diff`), Next.js reviewer diff pane (`amendment-section.tsx`), provision timeline component (`provision-timeline.tsx`), baseline code drawer integration.
  - [x] Full test pass: 985 Python non-integration tests, 25 Vitest files (133 tests), mypy clean, ruff clean.

---

## 🚀 Deployment Track (Google Cloud Platform) - Deferred
- [ ] **Minor Fix**: Update `infra/gcp/vm-setup.sh` step 6 to run from `/` or with `runuser -l` to avoid false-positive error reporting.
- [ ] **VM Pre-Flight**:
  - [ ] Test Cloud SQL reachability on port 5432 from VM.
  - [ ] Test Secret Manager access (`taxresearch-env`, `taxresearch-db-admin`).
- [ ] **First Deployment Run**:
  - [ ] Trigger manual GitHub Actions "Deploy to GCP" workflow.
  - [ ] Verify image build and remote `deploy.sh` execution.
- [ ] **Acceptance**:
  - [ ] Establish IAP tunnel (`gcloud compute start-iap-tunnel`).
  - [ ] Verify `/ready` returns 200.
  - [ ] Log in as first admin user.
