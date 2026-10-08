# M2 plan: Fetch, parse, store

Status: **approved by the user on 2026-10-08 (frozen)** · Milestone: TSD 13.2 M2 · Workstream B

## Goal

Exit criteria (TSD 13.2): "Loaders for CBIC portal and Supreme Court documents (files and fetch-by-URL) end to end to `blocks`. Dedup. Manual + fetch-by-URL loaders. Page accounting and cross-check."

When M2 is done, a platform user can hand the system a CBIC or Supreme Court document as a file or a URL. The worker then:

1. stores the raw bytes once, content-addressed
2. de-duplicates it
3. extracts every page, with a recorded status per page
4. writes `blocks`, `page_extractions` and `page_texts`

Problems go to the `parse_failure` review queue. Every step is tracked in `ingestion_jobs`.

## Scope

### In

- **Pipeline stages 1, 2, 3 and 4** (TSD 5.2) as worker handlers:
  - `acquire`: discover, fetch and dedup combined. See decision 2.
  - `parse`: blocks, page accounting and cross-check.
- **Loaders:**
  - CLI: `ingest-file`, `ingest-url`.
  - Watch folder.
  - API: `POST /v1/platform/ingestion/url` and `GET /v1/platform/ingestion/jobs/{id}`.
- **Formats:** PDF in full. HTML with basic native structure. DOCX is deferred (decision 7).
- **Dedup** (TSD 5.4):
  - Layer 1 (byte hash): full.
  - Layer 2 (canonical ID): when the loader supplies identifying metadata.
  - Layer 3 (near-duplicate): simhash is computed and stored. Matching is deferred (decision 4).
- **Parsing** (TSD 5.5):
  - per-page text-layer test
  - two-engine cross-check (pypdfium2 against pdfplumber)
  - garble score
  - OCR of failing pages
  - paragraph blocks with `page`, `bbox`, `seq`, `para_label`
  - repeated header and footer flagged as boilerplate (kept)
  - simple two-column detection
  - tables as `table` and `table_row` blocks
  - language flag (Devanagari gives `hi`)
  - raw `page_texts` for every page
- **Quality gates:**
  - Page accounting: pages in = `page_extractions` rows out.
  - Failed or flagged pages, and parse errors, open a `parse_failure` review task. The document stays `pending_review`.
- **Word-recall harness** (TSD 5.13): `eval/extraction_recall.py` measures word recall against `*.expected.txt`, with a gate of 99.5% or more. It runs on synthetic fixtures now and on real fixtures when they are supplied.
- **Carry-overs from M0 and M1:**
  - Worker retries with backoff and marks a job poisoned after 3 failures (the runner never retried).
  - The worker reads `LOG_LEVEL`.
  - Compose `WATCH_FOLDER=/watch`. It currently points to `./watch` inside the container.
  - A worker test `conftest.py` that migrates the database, so the Postgres queue tests stop skipping.

### Out (deferred)

| Item | Where |
| --- | --- |
| Classify, segment, metadata extraction, review UI, dashboard | M3 |
| Near-duplicate matching (needs date and court metadata) | M3 |
| API file upload (the API has no object store; it arrives with the reviewer console) | M3 |
| DOCX parsing | M3, or when a source needs it |
| Scheduled crawling, robots and terms handling | P2 (A-29) |
| Textract fallback | production |

## Design decisions

1. **The loader supplies `source` and `doc_type`.**
   - Before classification (M3), the `documents` row still needs `doc_type`, `authority_rank` and `title`.
   - Every loader requires `--source` (a code from `config/sources.yaml`) and `--doc-type` (one of `notification`, `circular`, `instruction`, `order`, `judgement`, `act`, `rules`, `other`).
   - `authority_rank` comes from a new `doc_types:` map in `config/authority.yaml`.
   - `title` defaults to the file name or the last part of the URL path. A `--title` option overrides it.
   - M3's classifier may later correct all three.
2. **`acquire` combines fetch and dedup in one stage.** A `document_versions` row needs a `document_id`, so dedup has to happen before the version row is written. One transaction does both:
   - Hash the bytes.
   - Byte hash already seen: attach the source URL (`document_sources`), mark the job `skipped`, and stop.
   - Canonical ID supplied and known: add a new version to that document.
   - Otherwise: create a new document.
3. **Provisional canonical ID.** When no identifying metadata is supplied, `canonical_id = "unk:<sha256 first 16 hex>"`. M3 metadata extraction replaces it. When metadata is supplied (for example `--series CT --number 11 --year 2017`, or a circular number), the ID is built with `legal_core.ids`.
4. **Simhash now, matching later.** A 64-bit simhash of the normalised text (`legal_core.normalise_text`) is stored on `document_versions` at parse time. Near-duplicate matching needs date and court metadata, so it starts in M3.
5. **OCR: pypdfium2 renders, the Tesseract CLI reads.**
   - Each page that needs OCR is rendered at 300 dpi with pypdfium2.
   - Tesseract reads it with TSV output, which gives text plus a per-word confidence. `ocr_conf` is the page mean.
   - This differs from TSD 5.5, which says OCRmyPDF. OCRmyPDF works on whole files and doesn't report per-page confidence, which page accounting needs. OCRmyPDF stays in the image for later whole-file use.
6. **Thresholds live in `config/ingestion.yaml`:**
   - text density (characters per page area)
   - cross-check margin (5%)
   - garble threshold
   - minimum OCR confidence (60)
   - maximum download size (50 MB)
   - fetch timeout
7. **Formats.** Both target sources publish mainly PDF, and CBIC also publishes some HTML.
   - HTML is parsed with the standard-library `html.parser`: headings, paragraphs and tables become blocks. No new dependency.
   - DOCX is deferred.
8. **Fetch-by-URL safety.** URL fetches are triggered by people and run on the server, so:
   - Only `https` and `http` URLs are accepted.
   - The host must be in the source's `allowed_hosts` list. A new key in `sources.yaml` holds the official CBIC, Supreme Court and e-Gazette domains.
   - Redirects are followed only to allowed hosts.
   - Addresses that resolve to private or loopback IPs are refused.
   - Downloads have a size cap and a timeout, and use the user agent from `sources.yaml`.
9. **Database access in the worker** uses SQLAlchemy Core `Table` definitions (`worker/db.py`) on the existing sync engine. This matches the queue code, so the worker has no ORM and doesn't import from the API.
10. **Job flow.**
    - A loader creates an `ingestion_jobs` row (stage `acquire`, status `queued`) and enqueues `job_queue` (queue `ingest.acquire`, payload `{ingestion_job_id}`, idempotency key = the job ID).
    - `acquire` hands off to `ingest.parse`.
    - Each handler updates `stage`, `status`, `attempt`, `error_*`, `started_at` and `finished_at`.
    - The parse idempotency key is `(version_id, parser_version)`.
11. **Object key layout:**
    - Raw files: `raw/<sha256[0:2]>/<sha256>`, immutable.
    - Watch-folder files are read from disk, never moved into the store under their own name.
12. **Watch folder.**
    - The layout is `<watch>/<source_code>/<doc_type>/<file>`.
    - The worker scans every `poll_interval_seconds`.
    - A file that has stopped changing (its size and modification time are the same on two scans) is loaded, then moved to `<watch>/.done/` or `<watch>/.failed/` with a reason file.

## Files

- **Worker** (`apps/worker/worker/`):
  - `db.py`: Core table definitions and small repository functions.
  - `config.py`: loads `sources.yaml`, `authority.yaml` and `ingestion.yaml`.
  - `ingest/loaders.py`: shared "create job" code used by the CLI, the watch folder and the API.
  - `ingest/fetch.py`: safe HTTP fetch with httpx.
  - `ingest/acquire.py`: the acquire handler, including dedup.
  - `ingest/pdf.py`: per-page extraction, cross-check, garble score, OCR, blocks, tables, columns, boilerplate.
  - `ingest/html.py`
  - `ingest/simhash.py`
  - `ingest/parse.py`: the parse handler, page accounting and review tasks.
  - `watch.py`
  - `cli.py`
  - `__main__.py`: registers the handlers and runs the watch loop.
  - `runner.py`: retry with backoff.
  - `settings.py`
- **API:** `apps/api/app/routers/ingestion.py`. New permission `ingest.submit` for `platform_admin` and `platform_content_editor`. It writes `ingestion_jobs` and `job_queue` rows with raw SQL in the same transaction, and writes an audit row (`ingest.submit_url`).
- **Config:**
  - `config/ingestion.yaml` (new)
  - `config/sources.yaml`: `allowed_hosts` for `cbic_gst_portal`, `supreme_court` and `e_gazette`
  - `config/authority.yaml`: the `doc_types:` map
- **Dependencies:**
  - Worker `pyproject.toml`: `httpx`, `pdfplumber`, `pypdfium2`, `pillow`. They are already in the Dockerfile, but tests need them declared.
  - `requirements-dev.txt`: `fpdf2`, used only to build test PDFs.
- **Infra:** compose worker `WATCH_FOLDER=/watch`; `.env.example`; README section "Loading documents".
- **Eval:** `eval/extraction_recall.py` and synthetic fixtures generated by tests.
- **Tests:** `apps/worker/tests/` (unit and integration), `conftest.py` with migrations, and an API router test.

## Verification

- **Unit tests** (no database):
  - garble score
  - cross-check margin
  - density test
  - paragraph and line grouping
  - `para_label` detection
  - header and footer detection
  - two-column ordering
  - table rows
  - language flag
  - simhash: stable, and near texts give a small Hamming distance
  - HTML blocks
  - URL safety: scheme, host allow-list, private IP, redirect off the list, size cap (with a mocked transport)
  - provisional and real canonical IDs
  - runner retry and backoff
  - watch-folder stability check
- **Synthetic PDF fixtures** (built with fpdf2 and Pillow in tests):
  - born-digital, one column
  - two-column
  - a table
  - a page with a broken text layer (`(cid:` text)
  - a scanned page (image only)
- **Integration** (Postgres, `-m integration`):
  - Load a file with the CLI and run the worker handlers once (in-process). Check:
    - `document_versions`
    - `blocks` in reading order
    - one `page_extractions` row per page
    - `page_texts`
    - `ingestion_jobs` ends at `parse`/`done`
  - Load the same bytes again: the job is skipped and a `document_sources` row is added.
  - Same canonical ID with different bytes: a new version of the same document.
  - Broken-text-layer page: flagged, OCR'd if Tesseract is available, and a `parse_failure` task opened if it still fails.
  - URL loader through the API with a local HTTP test server, allowed through a test-only host allow-list.
  - The Postgres queue tests now run instead of skipping.
- **OCR tests** need the `tesseract` binary. They skip when it is missing. The CI integration job will install `tesseract-ocr` (about 15 seconds) so they run there.
- **Recall harness:** synthetic born-digital fixtures must reach 99.5% or more.
- **Repo checks:** ruff, ruff format, mypy strict, all unit tests, and the integration tests against local Postgres 16.

## Decisions on open questions (user, 2026-10-08)

1. Real sample documents: approved to download 3 to 5 public documents from the official sites into `eval/fixtures/`. Synthetic fixtures remain the CI baseline.
2. API file upload: deferred to M3.
3. OCR: Tesseract CLI per page (decision 5).
