# M4c Slice 1 — Dry-run diff, Review Task Decision & Consolidation Engine

**Status: approved by the user on 2026-10-10 (frozen).**

Refs: `TSD.md` 4.10, 5.7, 5.9, 13.2; `docs/plans/M4-amendment-engine-and-baseline.md`; `docs/HANDOFF.md`.

## Goal

Complete the backend and worker automation for Milestone 4c:
1. Connect the deterministic applier (`amend_apply.py`) to the amendment detection stage (`detect_amendments.py`), computing `dry_run_ok` and `dry_run_diff` against current provision text.
2. Extend the review tasks API (`apps/api/app/routers/review_tasks.py`) to support decisions on `amendment` tasks (`approve`, `edit_approve`, `reject`, `needs_info`), updating the `amendments` table, capturing reviewer overrides in task resolution, and enqueuing consolidation.
3. Map `consolidation_runs` and `links` in `apps/worker/worker/db.py`.
4. Build the consolidation stage (`apps/worker/worker/ingest/consolidate.py`) for queue `ingest.consolidate`, replaying approved amendments via `plan_timeline`, managing bi-temporal intervals (`rec_to`, `rec_from`), inserting new `provision_versions`, logging consolidation runs, bumping `corpus_versions`, and writing typed `links`.

---

## Detailed Design & Changes

### 1. Dry-Run Diff in Amendment Detection (`apps/worker/worker/ingest/detect_amendments.py`)
- When an amendment proposal's target provision is resolved (`target_provision_id is not None`):
  - Look up the provision's latest valid version text in `provision_versions` (`rec_to IS NULL` and `valid_from <= effective_day`).
  - Convert proposal to `AppliedOp` using `op_from_amendment(proposal.op, proposal.old_text, proposal.new_text, locator)`.
  - Execute `apply_op(current_text, applied_op)`.
  - Populate `dry_run_ok = result.ok` and `dry_run_diff = result.diff if result.ok else (result.reason or "dry_run_failed")`.
- If target is unresolved or `apply_op` returns `ok = False`:
  - `dry_run_ok = False`.
  - Review task is opened with high priority (`priority = 1`, as specified in TSD 5.7 step 6).
  - Add failure reason to `problems_list`.

### 2. Review Task Decision for Amendments (`apps/api/app/routers/review_tasks.py`)
- For review tasks with `kind == "amendment"` and `subject_type == "amendment"`:
  - Subject ID is the `amendment_id`.
  - **Decision handling**:
    - `approve`:
      - Update `amendments`: `review_status = 'approved'`, `reviewer_id = actor.id`, `reviewed_at = now`, `review_note = body.note`.
      - Close task (`status = 'done'`, `closed_at = now`).
      - If amendment has target provision and is effective (`effective_from is not None` and not pending notification):
        - Enqueue `ingest.consolidate` with `{ "amendment_id": str(amendment_id), "instrument_id": str(instrument_id), "provision_id": str(target_provision_id) }`.
    - `edit_approve`:
      - Accept editable fields in `body.fields`: `op`, `old_text`, `new_text`, `effective_from`, `effective_condition`, `target_provision_id`.
      - Preserve original proposal in `task.resolution["original_proposal"]` (per frozen rule: no new column on `amendments`).
      - Update `amendments` with edited values and `review_status = 'approved'`.
      - Recompute `dry_run_ok` and `dry_run_diff`.
      - Close task (`status = 'done'`, `closed_at = now`).
      - Enqueue `ingest.consolidate`.
    - `reject`:
      - Update `amendments`: `review_status = 'rejected'`, `reviewer_id = actor.id`, `reviewed_at = now`, `review_note = body.note`.
      - Close task (`status = 'rejected'`, `closed_at = now`).
    - `needs_info`:
      - Update `amendments`: `review_status = 'needs_info'`.
      - Set task `status = 'in_review'`, `resolution["needs_info"] = True`.
  - Record audit log: `review.decision` with `object_type = 'review_task'`, detail including `amendment_id`, action, and fields.

### 3. Database Table Definitions (`apps/worker/worker/db.py`)
- Add SQLAlchemy Core table mappings matching migration `0005_legal_structure.py`:
  - `consolidation_runs`: `id`, `instrument_id`, `triggered_by_amendment_id`, `started_at`, `finished_at`, `versions_written`, `status`, `diff_summary`, `created_at`, `updated_at`.
  - `links`: `id`, `src_type`, `src_id`, `dst_type`, `dst_id`, `link_type`, `effective_from`, `effective_to`, `source_block_id`, `confidence`, `review_status`, `origin`, `updated_by`, `created_at`, `updated_at`.

### 4. Consolidation Stage (`apps/worker/worker/ingest/consolidate.py`)
- **Queue**: Define `CONSOLIDATE_QUEUE = "ingest.consolidate"` in `worker/ingest/queues.py`.
- **Payload**: `{"instrument_id": str, "provision_id": str, "amendment_id": str | None}`.
- **Workflow in transaction**:
  1. Query instrument and provision details.
  2. Query baseline version for the provision (`origin = 'baseline'`).
  3. Query all approved amendments for this provision (`review_status = 'approved'`), ordered by `effective_from ASC`, instrument issue date, and document ID.
  4. Call `plan_timeline(baseline_text, baseline_from, steps)` to generate the deterministic version intervals.
  5. Apply bi-temporal version changes:
     - Query existing active versions (`rec_to IS NULL`).
     - Compare with planned intervals. For superseded or altered intervals, update `rec_to = now()`.
     - For new intervals, insert rows into `provision_versions` with `rec_from = now()`, `rec_to = NULL`, `origin = 'amendment'`, `created_by_amendment_id = step.amendment_id`, `text_sha256 = sha256(text)`.
  6. Mark applied amendments: `applied_at = now()`.
  7. Insert a record into `consolidation_runs` with status `'done'`, `versions_written`, and summary.
  8. Bump `corpus_versions` (`INSERT INTO corpus_versions (reason)`).
  9. Insert typed `links` edges (e.g. `src_type='document'`, `dst_type='provision'`, `link_type=op_link_type`, `effective_from=...`, `review_status='approved'`).
  10. If operation is rescission or supersession, insert into `document_status_history`.
- Register handler `make_consolidate_handler` in `apps/worker/worker/__main__.py`.

---

## Files to Change / Create

1. `apps/worker/worker/db.py`: Add `consolidation_runs` and `links` table definitions.
2. `apps/worker/worker/ingest/queues.py`: Add `CONSOLIDATE_QUEUE = "ingest.consolidate"`.
3. `apps/worker/worker/ingest/detect_amendments.py`: Compute `dry_run_ok` and `dry_run_diff` for resolved proposals.
4. `apps/worker/worker/ingest/consolidate.py`: (New file) Consolidation worker logic.
5. `apps/worker/worker/__main__.py`: Register `CONSOLIDATE_QUEUE` and handler.
6. `apps/api/app/routers/review_tasks.py`: Add decision branch for amendment tasks.
7. `apps/worker/tests/test_amend_dry_run.py`: (New test file) Unit tests for dry run diff generation.
8. `apps/worker/tests/test_consolidate.py`: (New test file) Unit tests for consolidation logic and interval generation.
9. `apps/api/tests/test_review_tasks_amendments.py`: (New test file) Unit tests for amendment decision handling and queueing.

---

## Out of Scope for Slice 1 (Reserved for Slice 2)

- Point-in-time public REST API endpoints (`/v1/provisions/.../timeline`, `/v1/provisions/.../diff`).
- Reviewer console web diff viewer (`amendment-section.tsx`) and Next.js timeline UI.
- Rates tables (`hsn_sac_rates`) and back-fill CLI runner.

---

## Verification Plan

1. Code hygiene:
   - `ruff check .`
   - `ruff format --check .`
   - `mypy apps/worker apps/api packages/legal-core/src`
2. Unit tests:
   - Run new dry-run diff tests: `pytest -q apps/worker/tests/test_amend_dry_run.py`
   - Run new consolidation tests: `pytest -q apps/worker/tests/test_consolidate.py`
   - Run new review tasks amendment decision tests: `pytest -q apps/api/tests/test_review_tasks_amendments.py`
   - Run full unit test suite: `pytest -q -m "not integration"`
