# M5 — Search and Retrieval

**Status: approved by the user on 2026-10-10 (frozen).**

Refs: `TSD.md` 4.5, 4.7, 5.10, 6.1–6.10, 8.2, 13.2; `config/retrieval.yaml`; `config/synonyms.yaml`.

---

## Goal

Build the complete Search and Retrieval subsystem for the TaxResearch platform:
1. **Legal-structure chunking & FTS indexing pipeline** generating bi-temporal `chunks` with PostgreSQL `tsvector` and GIN indexing.
2. **Citation mention indexer** scanning documents for legal references and recording `mentions` links.
3. **Deterministic citation parser & resolver** (`GET /v1/resolve`) mapping citation queries directly to provision and document entities.
4. **Search and ranking engine** with point-in-time `as_on` filtering, query expansion (`config/synonyms.yaml`), authority / jurisdiction / recency / status weighting (`config/retrieval.yaml`), document deduplication, and snippet highlighting.
5. **REST APIs** (`GET /v1/search`, `GET /v1/resolve`, `GET /v1/provisions/{id}/linked`).
6. **Web console search interface** with as-on date selector, citation detector, faceted filters, and grouped search results with binding/authority badges.

---

## Execution Plan by Slices

### Slice 1: Chunking, Indexing Pipeline & Mention Indexer (Worker & Core)
- **Database Mapping**:
  - Map `chunks` table in `apps/worker/worker/db.py` matching migration `0005_legal_structure.py`.
- **Chunk Generator (`apps/worker/worker/ingest/chunking.py`)**:
  - Implement legal structure chunking per TSD 6.2:
    - **Leaf Provision Versions**: One chunk per leaf provision version (sub-section with clauses and provisos). Heading path e.g. `CGST Act > Chapter V > s.16 > (2) > (c)`. Target ≤ 600 tokens. Parent summary chunks for sections.
    - **Notifications**: One chunk per numbered paragraph, preamble chunk with parent act / date.
    - **Circulars / Orders**: One chunk per paragraph (merge paragraphs under 80 tokens).
    - **Judgements**: Paragraph groups within section labels (facts, issues, findings, order).
  - Copy validity intervals (`valid_from`, `valid_to`) and metadata (`doc_type`, `authority_rank`, `court_level`, `state_code`, `is_current`) directly onto chunks.
  - Generate PostgreSQL `tsvector` with weighted components (Heading / Title: Weight A, Body Text: Weight B).
- **Indexing Stage & CLI (`apps/worker/worker/ingest/index_chunks.py`)**:
  - Register `INDEX_QUEUE = "ingest.index"` in `apps/worker/worker/ingest/queues.py`.
  - Automatically enqueue indexing on document publish and provision consolidation.
  - CLI commands in `apps/worker/worker/cli.py` (`index-document`, `index-provisions`, `reindex-all`).
- **Mention Indexer (`apps/worker/worker/ingest/mentions.py`)**:
  - Scans published document text blocks for provision citations.
  - Resolves citations to `provisions.id`.
  - Inserts `links` rows (`src_type = 'document'`, `dst_type = 'provision'`, `link_type = 'mentions'`, `review_status = 'approved'`).
- **Testing & Verification**:
  - Unit tests for chunking across Acts, Rules, Notifications, Circulars, Judgements.
  - Unit tests for tsvector generation and GIN query matching.
  - Unit tests for citation mention extraction and link creation.

---

### Slice 2: Citation Resolver, Search Ranking Engine & REST APIs (API & Core)
- **Citation Resolver (`GET /v1/resolve`)**:
  - Extend Lark/regex parser in `packages/legal-core/src/legal_core/citations.py` to support query citation strings:
    - Provisions: `s.16(2)(c) CGST`, `sec 16(2)(c)`, `rule 36(4)`, `r.36(4)`.
    - Notifications: `Notf 11/2017-CT(R)`, `11/2017-Central Tax (Rate)`.
    - Circulars: `Circular 183/15/2022`.
  - Router `apps/api/app/routers/resolve.py` returning `{kind, canonical_id, target_id, confidence, alternatives[]}`.
- **Query Expansion Engine (`apps/api/app/modules/search/expansion.py`)**:
  - Load `config/synonyms.yaml` (abbreviations like ITC, RCM, GSTR).
  - Expand input query terms into alternate synonym terms with lower weighting.
  - Support `expand=true|false` parameter; return `expanded_terms` in response.
- **Search & Ranking Engine (`apps/api/app/modules/search/engine.py`)**:
  - PostgreSQL FTS with `websearch_to_tsquery('english', :query)`.
  - Point-in-time `as_on` filtering (TSD 6.5):
    - Provisions: `valid_from <= as_on AND (valid_to IS NULL OR valid_to > as_on)`.
    - Notifications/Circulars: `in_force_date <= as_on` with status history check.
  - Multi-factor scoring formula (TSD 6.6 & `config/retrieval.yaml`):
    `score = ts_rank_cd(tsv, q) * auth(c) * juris(c) * recency(c) * statusf(c)`.
  - Result deduplication: Collapse multiple passages per document into best chunk with child passage count.
  - Snippet highlights via `ts_headline`.
  - Grouped results by doc type with exact counts.
  - Keyset / cursor pagination with no total result cap (FR-RES-15).
- **Search REST APIs (`apps/api/app/routers/search.py`)**:
  - `GET /v1/search`: query params `q`, `as_on`, `types`, `court`, `state`, `date_from`, `date_to`, `topic`, `expand`, `limit`, `cursor`.
  - `GET /v1/provisions/{id}/linked`: linked amending instruments, issued-under notifications, clarifying circulars, interpreting judgements, mentions (TSD 6.10).
- **Permissions**:
  - Add `"search.read"` to `_ANY_USER` in `apps/api/app/auth/permissions.py`.
- **Testing & Verification**:
  - Comprehensive unit test suite with 50+ citation test cases.
  - Search engine query tests (phrase, Boolean, point-in-time filtering, authority ranking, deduplication).
  - Linked provisions API tests.

---

### Slice 3: Search Console UI (Next.js Frontend)
- **API Client & Types**:
  - Export OpenAPI schema and regenerate TypeScript definitions (`npm run gen:api`).
- **Search Page & Components (`apps/web`)**:
  - Search bar with real-time citation detection banner.
  - Point-in-time `as_on` date picker (defaults to today in IST).
  - Query expansion tags ("Also searched: Input Tax Credit").
  - Filter sidebar (document types, authorities, date ranges, topics).
  - Grouped results view (`search-results.tsx`) showing sections, notifications, circulars, judgements with binding/authority badges and expandable child passages.
- **Linked Documents Panel (`provision-linked.tsx`)**:
  - Display all linked instruments and mentions on provision view pages.
- **Testing & Verification**:
  - Vitest component tests in `apps/web`.
  - Typecheck (`tsc --noEmit`) and lint (`eslint`) passes.

---

## Acceptance Criteria
1. Full test suite passing (`pytest -q -m "not integration"`).
2. Vitest test suite passing in `apps/web`.
3. Type checks clean (`mypy` and `tsc --noEmit`).
4. Code formatting and linting clean (`ruff check .`, `ruff format --check .`, `npm run lint`).
5. All sensitive data rules obeyed (synthetic data only, no secrets).
