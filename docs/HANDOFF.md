# Hand-off: where the build stands

Last updated: 2026-10-08, end of the session that delivered M1 to M3. The next session starts at **M4**.

## Workflow rules (from CLAUDE.md and the user)

- **Plan, freeze, code.** Write a plan in `docs/plans/`. Get explicit user approval and mark the plan file "approved by the user on <date> (frozen)". Implementers check that line before they code. If scope has to change, stop and re-plan with the user.
- **Cost-aware delegation.**
  - `explorer` (Sonnet) does exploration.
  - `implementer` (Haiku) does coding.
  - The main session keeps planning, review and the final checks.
  - Give implementers exact specs and separate file ownership when they run in parallel.
  - Don't add a `conftest.py` under `apps/worker/tests`. It clashes with `apps/api/tests/conftest.py` under importlib import mode.
- **CI minutes are limited.**
  - CI runs only on pull requests, pushes to `main` and manual dispatch. Docs-only changes are skipped.
  - Playwright e2e runs on pull requests only.
  - Commit locally and **push once at the end of a session or milestone**, or when the user asks.

## Milestones

| Milestone | Status | Plan | Main commits |
| --- | --- | --- | --- |
| M0 Foundations | Done. Container check on the Debian host still open. | (audit only) | `ac54abd`, fixes `7c46477` |
| M1 Core data and auth | Done | `docs/plans/M1-core-data-and-auth.md` | `6d46afd` to `0a9628e` |
| M2 Fetch, parse, store | Done | `docs/plans/M2-fetch-parse-store.md` | `70dc8bc`, `36a95c4`, `195fe19` |
| M3a Backend: structure and metadata | Done | `docs/plans/M3-structure-and-metadata.md` | `529cc72`, `bdb86f2` |
| M3b Reviewer console | Done (see the M3b notes in the plan) | same | `b24bd7d` onwards |
| **M4 Amendment engine and baseline law** | **Next: needs a plan and approval** | — | — |
| M5 to M8, P-1 to P-4 | Not started | TSD 13.2 | — |

Each plan file ends with "Review changes" and "Known gaps" sections. Read them before building on that milestone.

## What exists

- **Database:** migrations 0001 to 0007 cover every MVP table in TSD section 4, plus the dashboard views.
- **API** (`apps/api`):
  - auth: login, logout, `/v1/me`
  - admin users and audit
  - ingestion by URL and by upload, and job status
  - platform documents, sources, jobs and dashboard
  - review tasks
  - miss reports
  - CLI: `python -m app.cli create-user | verify-audit`
- **Worker** (`apps/worker`): the queue runner with retries, and a watch folder. Pipeline stages:
  1. acquire (fetch and dedup)
  2. parse (two engines, OCR, blocks, page accounting)
  3. classify
  4. segment (Lark numbering grammar)
  5. extract_meta
  6. apply_metadata
  7. publish

  CLI: `python -m worker.cli ingest-file | ingest-url | job-status | sample-audit`
- **Shared packages:** `packages/legal-core` (IDs, citations, text) and `packages/storage` (object store).
- **Web** (`apps/web`): the Next.js reviewer console, with login, the review queue and task view, the dashboard, documents and ingest pages.
- **Config** (`config/`): `sources.yaml` (with `allowed_hosts`), `authority.yaml` (with `doc_types`), `ingestion.yaml`, `courts.yaml` (DRAFT), and `citation_aliases.yaml` (series and case patterns are partly DRAFT).

## Setting up a fresh session container

The container is temporary. None of the following survives a new session.

```bash
# 1. Tesseract (needed for the OCR tests)
apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-eng

# 2. Postgres 16 (installed in the image) on port 55432, data outside the scratchpad
D=/var/lib/postgresql/m1
su postgres -c "/usr/lib/postgresql/16/bin/initdb -D $D/data -A trust -U postgres && \
  /usr/lib/postgresql/16/bin/pg_ctl -D $D/data -o '-k $D -p 55432 -c listen_addresses=localhost' -l $D/log start -w"
P="psql -h localhost -p 55432 -U postgres"
$P -c "create role taxresearch_test login password 'test-password-ci'"
$P -c "create database taxresearch_test owner taxresearch_test"
$P -d taxresearch_test -c "create extension citext; create extension ltree; create extension pg_trgm; create extension btree_gist;"
export DATABASE_URL=postgresql://taxresearch_test:test-password-ci@localhost:55432/taxresearch_test

# 3. Python venv (3.12+), with the dev requirements and every app and package in editable mode
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
for p in apps/api apps/worker packages/legal-core packages/storage; do pip install -e $p; done

# 4. Web
(cd apps/web && npm ci)
```

The test role isn't a superuser, so the extensions are created as `postgres` before the migrations run.

## Running checks

```bash
ruff check . && ruff format --check . && mypy
pytest -q -m "not integration"
DATABASE_URL=... pytest -q -m integration            # runs migrations itself
(cd apps/web && npm run lint && npm run typecheck && npm test && npm run build)
scripts/e2e-stack.sh && (cd apps/web && PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers npx playwright test); scripts/e2e-stack.sh stop
```

## Waiting on the user

1. **Debian host check.** Image builds and the stack have never run under Podman. Run `scripts/up.sh`, then `scripts/verify.sh`, then `python -m app.cli create-user ... --role platform_admin`.
2. **Real sample documents.** The session network policy blocked `cbic-gst.gov.in`, `taxinformation.cbic.gov.in`, `www.sci.gov.in` and `egazette.gov.in`. Either allow them in the environment settings, or put 3 to 5 PDFs in `eval/fixtures/`. Everything so far has been tested on synthetic PDFs only.
3. **Experts.**
   - The query set is needed before M5.
   - The fixture set is needed before M7.
   - Review the DRAFT `config/courts.yaml`, the series aliases and the case-number patterns (A-26).
   - Verified baseline Act and Rules text is needed for M4 (A-17).
4. **CI has never run on GitHub.** It will run on the first pull request or merge to `main`.

## Starting points for M4 (TSD 13.2, 4.4, 4.10, 5.7, 5.9)

M4 covers: baseline Acts (CGST, IGST) and CGST Rules, loaded and verified; the amendment detector (Lark pattern grammar); the dry-run applier; the amendment review view (with a diff pane in the console); consolidation; point-in-time APIs; version timeline and diff; back-fill since 1 July 2017; and rates tables.

What M4 can build on:
- Segment output for Acts and Rules: `blocks.structure_path` such as `ch5.s16.2.c`. This is the input for creating `provisions` and baseline `provision_versions`.
- Notification amending units: `structure_path` `p<n>.i<k>` (per block, not per sentence; see the M3a known gaps).
- Tables already exist from 0005: `provisions`, `provision_versions` (with the `pv_no_overlap` exclusion constraint), `amendments`, `consolidation_runs`, `links`, `hsn_sac_codes` and `hsn_sac_rates`.
- The review queue and console are generic. M4 adds the `amendment` kind view and the dry-run diff pane.
- `legal_core.citations` is still regex. M4 target resolution may need the Lark citation parser early, which TSD puts in M5.

Decisions for the M4 plan:
- Where the verified baseline text comes from (expert-supplied files, or our own segmented PDFs verified in the console).
- Whether to pull the Lark citation parser forward from M5.
- How much of the back-fill since July 2017 is in scope for the POC.
