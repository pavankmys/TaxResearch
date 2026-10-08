# M3 plan: Structure and metadata

Status: **approved by the user on 2026-10-08 (frozen)** · Milestone: TSD 13.2 M3 · Workstreams B, F

## Goal

Exit criteria (TSD 13.2): "Segmentation for Acts, Rules, notifications, circulars, judgements. Metadata extraction (rule-based). Review queue UI (metadata, parse failure, miss report). Ingestion dashboard."

When M3 is done:

1. A parsed document is classified, segmented (`blocks.structure_path` and section labels) and has its metadata extracted by rules. It is then published as `auto_published` (confident) or `pending_review`.
2. Low-confidence metadata, numbering problems and parse failures land in one review queue.
3. A platform content editor works that queue in a web console:
   - left: the source page image at the block
   - centre: the proposal
   - actions: approve, edit then approve, reject, needs info
4. The console has the ingestion dashboard (TSD 5.11) and a document page for fixing metadata.

## Split into two parts

M3 is about twice the size of M2, because the web app is still a bare health page. I propose two parts, approved together and built and pushed in order.

- **M3a: backend.** Pipeline stages, segmentation, metadata, near-duplicate matching, the review/dashboard/document/source/upload APIs, and the shared storage package.
- **M3b: reviewer console.** The Next.js UI, login, queue, task view, dashboard, documents and ingest pages, plus tests.

Each part ends with its own review and push.

## Scope

### M3a: backend

- **Pipeline stages 5 to 8** (TSD 5.2) as worker handlers chained after `parse`: `classify`, then `segment`, then `extract_meta`, then `publish`. Each is idempotent on `(version_id, <stage>_version)`.
- **Classify** (rules; decision 2). Decides the doc type and authority rank. The loader's `doc_type` is a hint.
- **Segment** (TSD 5.5):
  - Acts and Rules: Lark grammar over numbering (chapter, `16.`, `(2)`, `(c)`, `(i)`, "Provided that", "Explanation"). Sets `structure_path` (decision 3). Forms and annexures are separate blocks.
  - Notifications: preamble, numbered paragraphs, schedules and table rows. Amending paragraphs are split into one unit per instruction, as text only; parsing the instructions is M4.
  - Circulars: header (number, date, subject, DIN), then numbered paragraphs.
  - Judgements: header (court, bench, parties, case numbers, date), then paragraphs. Section labels (facts, issues, arguments, findings, order) come from heading patterns. Printed paragraph numbers are kept.
  - Quality gate: gaps, duplicates or a non-monotonic sequence in numbering open a `parse_failure` task with the problem highlighted.
- **Extract metadata** (TSD 5.6):
  - Rule extractors per type. The output is a Pydantic schema with a confidence for each field.
  - Cross-checks: number against file name or title; dates plausible (on or after 2017-06-01 for GST instruments, not in the future); court in `config/courts.yaml`.
  - Document confidence = the minimum over required fields. Below 0.85 opens a `metadata` task.
  - Writes `documents` and the typed tables (`notifications`, `circulars`, `judgements`).
  - Replaces the provisional `unk:` canonical ID.
- **Near-duplicate matching** (deferred from M2; TSD 5.4 layer 3):
  - Match: simhash within Hamming distance 3, plus the same date (and the same court for judgements).
  - Auto-merge when the case or document number also matches, by moving the version to the existing document.
  - Otherwise open a `metadata` task naming both documents.
  - The same applies when the extracted canonical ID collides with an existing document.
- **Publish:**
  - Sets `review_state` (`auto_published` when no open tasks and confidence is at least 0.85, else `pending_review`).
  - Sets the job's `published_at`.
  - Bumps `corpus_versions`.
  - Writes the first `document_status_history` row (`in_force` from the in-force date or issue date).
- **Review assignment:** new tasks go round-robin to active `platform_content_editor` users (TSD 5.8). An 8 h SLA applies to amendment tasks only (M4); other kinds get none.
- **APIs** (TSD 8.2):
  - `GET /v1/platform/review-tasks`: filters for kind, status, assignee and source; keyset pagination.
  - `GET /v1/platform/review-tasks/{id}`: the task plus its context (document, version, metadata proposal with field confidences, problem pages and blocks, near-duplicate candidate).
  - `POST /v1/platform/review-tasks/{id}/assign`
  - `POST /v1/platform/review-tasks/{id}/decision`: approve, edit_approve, reject or needs_info.
    - Edits are stored as a reviewer override; the original stays in `resolution`.
    - Approving a metadata edit applies it to the document.
    - Every decision is audited.
    - When a document's last open task closes, it moves to `reviewed`.
  - `GET /v1/platform/documents/{id}`, `PATCH /v1/platform/documents/{id}`: fix metadata and set status; audited.
  - `GET /v1/platform/documents/{id}/versions/{vid}/pages/{n}.png`: page image rendered on demand at 110 dpi, cached in the object store.
  - `GET /v1/platform/documents/{id}/versions/{vid}/raw`: the original file.
  - `GET /v1/platform/sources`, `PATCH /v1/platform/sources/{code}`: enable or disable a source and set its cadence.
  - `POST /v1/platform/ingestion/manual`: multipart file upload (deferred from M2), with a 50 MB cap and type sniffing.
  - `POST /v1/platform/jobs/{id}/retry`
  - `GET /v1/platform/ingestion/dashboard`
  - `POST /v1/miss-reports`: any signed-in user. It opens a `miss_report` task holding the query, filters and as-on date. The search UI that calls it comes in M5 and M6.
- **Dashboard:**
  - Migration 0007 adds SQL views for:
    - counts per source per day by status
    - freshness p50 and p95
    - source health against cadence
    - queue depth and age by kind
    - page accounting (failed and flagged pages)
    - cross-check disagreements
    - queue lag
  - Numbering gaps show "not yet measured" until M7.
- **Config** (draft values, marked for expert review under A-26):
  - `config/courts.yaml`: Supreme Court, High Courts, GSTAT and AAR/AAAR codes and names.
  - `citation_aliases.yaml`: series IT, IT(R), UT, UT(R), COMP, COMP(R).
  - Case-number patterns: SLP, CA, WP, WP(C) and Tax Appeal.
- **Shared storage package** (decision 6): `packages/storage` holds the ObjectStore code that both the worker and the API use.
- **Spot-check audit** (TSD 5.6 step 4): the CLI command `worker sample-audit --percent 2` queues spot-check tasks. Scheduling it weekly is M7.

### M3b: reviewer console

- **Stack** (TSD 3.1): Next.js 15, Tailwind and shadcn/ui (Radix). TypeScript types are generated from the API's OpenAPI spec with `openapi-typescript`, and calls go through a small typed fetch wrapper.
- **Auth:**
  - The login page posts to a Next route handler, which calls `/v1/auth/login` and stores the JWT in an `httpOnly`, `Secure`, `SameSite=Strict` cookie.
  - The browser never sees the token. Server components and route handlers forward it to the API.
  - Middleware redirects to the login page when there is no session.
  - Logout clears the cookie and calls `/v1/auth/logout`.
- **Pages:**
  - Review queue: filters, a "My tasks" tab, priority and age, keyboard navigation.
  - Task view: page image with the block highlighted (from `bbox`); the proposal with per-field confidence; an edit form; approve, edit then approve, reject and needs-info with a note. Variants:
    - parse failure: page status and reasons, plus the page text fallback
    - miss report: query, filters, as-on date
    - near duplicate: the two documents side by side
  - Dashboard: metric tiles and per-source tables.
  - Documents: list and detail (metadata, versions, blocks by `structure_path`, raw file link, status edit).
  - Ingest: by URL and by file upload; job status polling.
- **Roles:** only `platform_content_editor` and `platform_admin` see the console. Other users get a "no access" page.
- **Accessibility** (NFR-12, WCAG 2.1 AA): semantic landmarks, labelled form controls, focus management, colour contrast. Checked with axe in the Playwright tests.
- **Tests:**
  - Vitest for components and helpers.
  - Playwright end to end against the real API, the worker and Postgres. It runs the stack locally and covers: log in, ingest a fixture, see it in the queue, approve an edit, see the dashboard counts change.
  - In CI, Playwright runs only on pull requests, and the web job adds `npm run build`. This keeps minutes low.

### Out (deferred)

| Item | Where |
| --- | --- |
| Amendment detection, the amendment review view, the dry-run diff pane | M4 |
| Writing `provisions` and baseline `provision_versions` from Act and Rules segments | M4 (A-17: baselines are verified by editors) |
| Lark citation parser for search queries; checking that referred sections exist | M5 (no provisions until M4) |
| Numbering-gap detection, coverage and scheduled jobs | M7 |
| DOCX | when a source needs it |

## Design decisions

1. **One stage per worker queue** (`ingest.classify`, `ingest.segment`, `ingest.extract_meta`, `ingest.publish`), chained like acquire and parse. `ingestion_jobs.stage` tracks progress. Re-running a stage replaces its derived rows. Version keys `segmenter_version` and `extractor_version` go in the job payload, and on `document_versions` through migration 0007.
2. **Classification order:**
   1. Strong header cues: "Notification No.", "Circular No.", "Instruction No.", "Order No.", "IN THE SUPREME COURT OF INDIA", "IN THE HIGH COURT OF", "THE ... ACT, 20xx", "... RULES, 20xx".
   2. Otherwise the loader's hint.
   3. If a strong cue disagrees with the hint, the cue wins and a `metadata` task records the conflict.
3. **`structure_path` format:** dot-separated tokens, matching the provision ID path (`prov:CGST_ACT:s16.2.c`).
   - Acts: `ch5.s16.2.c`, `s16.2.c.prov1`, `s16.expl1`
   - Rules: `r36.4`
   - Notifications: `pre`, `p3`, `p3.i2` (instruction 2 of paragraph 3), `sched1.row12`
   - Circulars: `hdr`, `p4.2`
   - Judgements: `hdr`, `facts.p12`, `order.p40`. The printed paragraph number stays in `para_label`.
4. **Metadata confidence per field** comes from the extraction rule: an exact header pattern is 0.95, a fallback pattern 0.7, an inference from the file name 0.5. A failed cross-check halves it.
5. **Reviewer overrides never overwrite the proposal.** `resolution` stores `{proposal, override, decided_by, decided_at, note}`. Changes made through `PATCH /documents` are audited with the before and after values.
6. **Shared storage package.** The API now needs the object store (page images, raw downloads, uploads). `worker/objectstore.py` moves to `packages/storage` (`taxresearch_storage`), and the worker re-exports it so imports keep working. Upload sniffing and limits live there too.
7. **Page images** are rendered by the API with pypdfium2 and cached in the object store under `derived/pages/<sha>/<n>-110.png`. They are served with `Cache-Control: private, max-age=3600`.
8. **Web login** uses a backend-for-frontend cookie, not a bearer token in the browser (TSD 8.1: "Same-site cookies for the web session"). The API stays bearer-only.

## Verification

- **M3a:**
  - Unit tests for each segmenter and extractor on synthetic texts: an Act with chapters, sections, provisos and explanations; a CT notification with amending paragraphs and a schedule; a circular with a DIN; a Supreme Court judgement header and labelled sections; numbering gaps and duplicates.
  - Classification cue tests.
  - Near-duplicate tests.
  - API tests: permissions, decisions, overrides kept, audit rows.
  - Integration: a file goes end to end from acquire through publish. Check `structure_path`, metadata, the typed table, `review_state`, `corpus_versions`, review tasks and assignment.
- **M3b:** lint, typecheck, Vitest, `next build`, and Playwright end to end with axe, all run locally.
- **Both:** ruff, format, mypy strict, and all unit and integration tests.
- **Real documents:** if network access to the official sites is enabled, CBIC and Supreme Court samples are added to `eval/fixtures/` and run end to end. Until then everything rests on synthetic fixtures.

## Decisions on open questions (user, 2026-10-08)

1. Split approved: M3a (backend), then M3b (console), each reviewed and pushed when done.
2. Draft config (courts, series aliases, case-number patterns) is written by us and marked for expert review (A-26).
3. Playwright runs in CI on pull requests only.

## Interfaces fixed for parallel implementation (M3a)

- **Migration 0007** (added columns):
  - `document_versions`: `segmenter_version text`, `extractor_version text`, `segmented_at timestamptz`, `extracted_at timestamptz`
  - `documents`: `metadata jsonb NOT NULL DEFAULT '{}'`, `meta_confidence real`
  - The dashboard views.
- **Metadata JSON** (stored in `documents.metadata` and in review task `resolution.proposal`):
  - `{"fields": {...}, "confidence": {...}, "issues": [...], "extractor_version": "..."}`
  - Field names:
    - common: `doc_type`, `title`, `number`, `series`, `year`, `doc_date`, `in_force_date`, `issuing_authority`, `canonical_id`, `sections_referred`
    - notification: `effective_date`, `gazette_ref`
    - circular: `circular_kind`, `subject`, `din`
    - judgement: `court_level`, `court_name`, `court_code`, `bench`, `judges`, `decision_date`, `parties` (`{"petitioners": [], "respondents": []}`), `case_numbers`, `reporter_citations`
- **One write path for metadata:** the worker job `ingest.apply_metadata`, payload `{document_id, fields, actor_user_id, reason, review_task_id|null}`. It is used by extraction, by review decisions (edit_approve) and by `PATCH /v1/platform/documents/{id}` (which returns 202). It writes `documents`, the typed table and `metadata`, then re-runs `publish`.

## M3a review changes and decisions

- **Worker writes no audit rows.** The audit chain stays API-only. The API audits review decisions and document edits before it enqueues `ingest.apply_metadata`.
- **Upload payloads in acquire.** `acquire` accepts `object_key` and `file_name` (from `POST /v1/platform/ingestion/manual`) and records the source as `upload://<file_name>`.
- **parse_failure priority is 2** (metadata 3, miss_report 4). Round-robin assignment is the same rule in the worker (`worker/review.py`) and the API (`app/review_assign.py`).
- **Storage is wired like legal-core.** The Dockerfiles and the CI editable install pull it in; it isn't declared in each app's `pyproject.toml`. S3 `exists()` now handles the 404 from `head_object` correctly.
- **Retrying an acquire job** reuses the original queue payload.
- **`PATCH /documents` returns 202.** Field changes go through `apply_metadata`; status changes are written directly, with history rows.
- **Classifier cues for Acts and Rules** match upper-case titles only.
- **Judgement case numbers** are stored in short form (for example `CA 1234/2020`); the first one goes into the canonical ID.

## M3a known gaps

- Segmentation works per block. When the PDF layout merges a section heading and "(1)", or merges paragraphs, the sub-items in that block get no path of their own. Amending notifications are split per block, not per sentence.
- Title, judge, bench and party extraction is heuristic. Parties depend on the `...Appellant(s)` line format.
- Acts keep a provisional `unk:` canonical ID until M4 creates provisions.
- Court lists, series aliases and case-number patterns are DRAFT until the experts review them (A-26).
- The pipeline is tested on synthetic documents only. Real CBIC and Supreme Court samples need network access or files from the user.

## M3b review changes and decisions

- **Login cookie.** `tr_session` is `httpOnly`, `SameSite=Strict` and `Secure` unless `COOKIE_SECURE=false` (needed for local http end-to-end runs). The token never reaches the browser. Page images and raw files go through Next route handlers, which check the IDs before forwarding.
- **Middleware security headers.** CSP, `X-Frame-Options: DENY`, `nosniff` and `Referrer-Policy`. `script-src` keeps `'unsafe-inline'` because Next's inline bootstrap scripts carry no nonce.
- **Upload limit.** `serverActions.bodySizeLimit` is 52 MB so file uploads reach the API's 50 MB cap.
- **e2e stack.** `scripts/e2e-stack.sh` gives the API and the worker the same local object store.
- **Pinned versions.** Tests use vitest 3.2.4 (npm 10.9 crashes installing 4.x). `@playwright/test` and `playwright-core` are pinned to 1.56.1, matching the preinstalled Chromium.
- **Job status.** A job is "terminal" when it has failed, been skipped at acquire, or is done at publish.
- **Form behaviour.**
  - Metadata and status forms call Server Actions inside `startTransition`, because `useActionState` left the button stuck on "Saving…".
  - Tabs read `?tab=` when the page loads but don't write it on click.
  - The metadata edit form only accepts new values; it can't clear a field.

## M3b known gaps

- **Keyboard.** The queue has no arrow-key navigation; the tab order works.
- **Highlights.** Metadata tasks show page 1 with no block highlighted, because the API returns no blocks for them.
- **User names.** "Reported by" and override authors show "You", "Another user" or a short user ID, because the APIs return only IDs.
- **"Last 24 h" tiles** use UTC calendar days (today and yesterday).
- **Not verified here.** The Docker image builds and the GitHub e2e job: this session has no container runtime, and CI hasn't run yet.
