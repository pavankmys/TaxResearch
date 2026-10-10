# M4c Slice 2 — Point-in-Time APIs, Version Timeline & Reviewer Console Diff Pane

**Status: frozen for execution on 2026-10-10.**

Refs: `TSD.md` 4.10, 5.7, 5.9, 6.8, 13.2; `docs/plans/M4-amendment-engine-and-baseline.md`; `docs/plans/M4c-slice1-consolidation-engine.md`.

## Goal

Complete Slice 2 of Milestone 4c:
1. Provide Point-in-Time REST APIs for provisions (`GET /v1/provisions/{id}`, `GET /v1/provisions/{id}/timeline`, `GET /v1/provisions/{id}/diff`).
2. Enrich review tasks API so `ReviewTaskDetail` includes typed `amendment` data (target provision path, current text, locator, diff).
3. Build the reviewer console diff viewer component (`amendment-section.tsx`) displaying side-by-side / inline colored word diffs and dry-run diagnostics.
4. Support reviewer edits for amendments in `TaskActions` for the `edit_approve` workflow.
5. Build the provision version timeline component to inspect chronological evolution of provisions.
6. Verify with unit tests, OpenAPI schema generation, Vitest, lint, and type check.

---

## Detailed Specification & Architecture

### 1. Point-in-Time & Provisions Router (`apps/api/app/routers/provisions.py`)
- **Prefix**: `/v1/provisions`, tags: `["provisions"]`.
- **Permissions**: Add `"provisions.read"` to `_ANY_USER` in `apps/api/app/auth/permissions.py`.
- **Endpoints**:
  - `GET /v1/provisions/{provision_id}`:
    - Path parameter: `provision_id: UUID`.
    - Query parameter: `as_on: date | None = None`.
    - If `as_on` is supplied, queries valid-time at date: `valid_from <= as_on AND (valid_to IS NULL OR valid_to > as_on) AND rec_to IS NULL`.
    - If `as_on` is omitted, queries current active version (`rec_to IS NULL AND (valid_to IS NULL OR valid_to > CURRENT_DATE)`).
    - Returns `ProvisionResponse` with provision metadata (`path`, `level`, `number_label`, `instrument_id`) and active `version` (`id`, `heading`, `text`, `valid_from`, `valid_to`, `origin`, `created_by_amendment_id`).
  - `GET /v1/provisions/{provision_id}/timeline`:
    - Queries all active versions: `WHERE provision_id = :id AND rec_to IS NULL ORDER BY valid_from ASC`.
    - Joins `amendments` and `documents` to populate amending document information (`number`, `title`, `doc_date`).
    - Returns `ProvisionTimelineResponse` containing list of `ProvisionTimelineItem`.
  - `GET /v1/provisions/{provision_id}/diff`:
    - Query parameters:
      - `from_date: date | None`, `to_date: date | None`
      - `from_version_id: UUID | None`, `to_version_id: UUID | None`
    - Resolves the two versions from `provision_versions`.
    - Uses `legal_core.amend_apply.word_diff(from_text, to_text)` to compute word diff.
    - Returns `ProvisionDiffResponse`: `from_version`, `to_version`, `identical`, `diff`, `additions_count`, `deletions_count`.

### 2. Task Details Enrichment (`apps/api/app/routers/review_tasks.py`)
- Add `AmendmentSummary` schema:
  - `id: UUID`, `source_document_id: UUID`, `op: str`, `target_provision_id: UUID | None`
  - `target_locator: dict[str, Any] | None`, `old_text: str | None`, `new_text: str | None`
  - `effective_from: date | None`, `effective_condition: str | None`
  - `dry_run_ok: bool | None`, `dry_run_diff: str | None`, `review_status: str`
  - `target_provision_path: str | None`, `current_provision_text: str | None`
- In `ReviewTaskDetail`, add `amendment: AmendmentSummary | None = None`.
- In `get_task`, if `subject_type == "amendment"` and `subject_id` is present, query amendment row, join `provisions` for path, query latest active version for `current_provision_text`, and populate `task.amendment`.

### 3. OpenAPI Schema Generation
- Run `npm run gen:api` in `apps/web` to synchronize `apps/web/lib/api-client/schema.d.ts` with the new endpoints and models.

### 4. Reviewer Console Frontend (`apps/web/components/review/amendment-section.tsx`)
- Create `amendment-section.tsx`:
  - **Status & Operation header**: Op badge (`substitute`, `insert`, `omit`, `raw`), confidence score, review status badge.
  - **Locator**: Instrument (`CGST_RULES`, `CGST_ACT`), provision path, resolution badge (Resolved / Unresolved).
  - **Dry-run diff box**:
    - If `dry_run_ok`: Formatted word diff viewer parsing `[-...-]` deletions (red background, strikethrough) and `{+...+} additions (green background, bold).
    - If `!dry_run_ok`: Alert banner highlighting `dry_run_diff` reason (e.g. `target_not_found`, `old_text_mismatch`, `unsupported_operation`) with resolution guidance.
  - **Provision preview**: Shows target provision path and current active text.
- Integrate into `apps/web/components/review/task-view.tsx` when `task.kind === "amendment"`.
- Extend `apps/web/components/review/edit-fields.ts` and `task-actions.tsx`:
  - Support editable amendment fields (`op`, `old_text`, `new_text`, `effective_from`, `effective_condition`, `target_provision_id`) when `kind === "amendment"` and `edit_approve` is selected.

### 5. Provision Version Timeline Component (`apps/web/components/provisions/provision-timeline.tsx`)
- Display version evolution over time:
  - Timeline cards for each version with badge for `origin` (`baseline` vs `amendment`), valid time range `[valid_from, valid_to]`.
  - Amending notification number, date, and link.
  - Interactive Diff toggle allowing the user to select any version to compare against.
- Integrate into baseline provision details panel in `apps/web/app/(console)/baseline/[code]/page.tsx`.

---

## Verification Plan

1. **Backend Tests**:
   - Create `apps/api/tests/test_provisions_api.py` testing `GET /v1/provisions/{id}`, `GET /v1/provisions/{id}/timeline`, `GET /v1/provisions/{id}/diff`, and `get_task` with amendment details.
2. **Frontend Tests**:
   - Create `apps/web/components/review/__tests__/amendment-section.test.tsx` verifying diff formatting and dry-run banners.
   - Run Vitest tests: `npm --prefix apps/web test`.
3. **Lint & Type Checks**:
   - Python: `ruff check .`, `ruff format --check .`, `mypy`.
   - Frontend: `npm --prefix apps/web run typecheck`, `npm --prefix apps/web run lint`.
4. **Integration/Non-regression**:
   - `pytest -q -m "not integration"` (all passing).
