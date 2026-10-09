# M4 — Amendment engine and baseline law

**Status: approved by the user on 2026-10-09 (frozen).** Scope changes during coding require stopping and re-planning with the user.

Refs: TSD 13.2, 4.4, 4.10, 5.7, 5.9; `docs/HANDOFF.md`.

## Goal

Load the expert-vetted baseline law (CGST Act, IGST Act, CGST Rules) as provisions with baseline versions. Detect amendments in notifications, propose them for human review, apply approved ones with a dry-run diff, and consolidate. Give point-in-time lookup, version timeline and diff. Back-fill all amending notifications since 1 July 2017. Rates tables are the last slice.

## Decisions taken (user, 2026-10-09)

1. Baseline text comes from the expert-vetted PDFs (kept in the user's Downloads folder; not committed). Reference by path only.
2. Pull the Lark citation parser forward from M5 (target resolution needs "section 16(2)(c)" style citations). Recommended by Claude, not objected to.
3. The CGST Act PDF is stated to be updated up to 11 June 2026, so no back-fill is needed for the CGST Act. The baseline is the consolidated text as at 11 June 2026, and amendments after that date are applied going forward. (This narrows the earlier "back-fill since July 2017" decision.)
4. M4 is built and tested locally. Debian/Podman and GCP deployment are out of scope here.
5. Rates input: the goods rate notification `09-2025-CTR-eng.pdf` is in the user's Downloads folder (56 pages). The user will supply the services rate notifications later.

## Open questions (need an answer before freeze)

- **Q1. IGST PDF — RESOLVED 2026-10-09.** The first file was the J&K extension Act (4 pages). The user replaced it. The file now in Downloads is the IGST Act, 2017 (Act 13 of 2017), 23 pages, "As on 1st September, 2026". Baseline as-on dates therefore differ per instrument (CGST Act 11 Jun 2026, IGST Act 1 Sep 2026). Each instrument's baseline `valid_from` for consolidation purposes is its own as-on date.
- **Q2. CGST Rules as-on date — RESOLVED 2026-10-09.** The Rules PDF is current only to 2019. The user will supply the later amending notifications. The Rules baseline therefore starts at its 2019 as-on date, and Rules back-fill runs from then to date over the notifications the user supplies. The Rules are the one instrument that needs a real back-fill.
- **Q3. Amendment input — RESOLVED 2026-10-09 (user: OK).** The detector, dry run and consolidation are proven on the sample notification, the Rules notifications the user supplies, and synthetic fixtures. Acts get future amendments only.
- **Q4. Rates scope — RESOLVED 2026-10-09.** Use only `09-2025-CTR-eng.pdf` for now. `ctr02-2025.pdf` is not an input. Services are added later by the user.

## Slices (each ends green on CI; commit locally, push at milestone end)

### M4a — Baseline load
- Migration 0008: add a `subclause` level (and any `provisions` columns the segmenter needs); seed `instruments` (CGST Act, IGST Act, CGST Rules).
- New worker stage `ingest.build_provisions` after `publish` for documents of type act or rules: turn `blocks.structure_path` into `provisions` rows and baseline `provision_versions` (`origin=baseline`, `valid_from` = the Act's or Rules' commencement). Idempotent via `idempotency_key`.
- Re-key the provisional `unk:` canonical IDs to real provision IDs.
- Console: baseline verification, with the reviewer approving each instrument's provision tree against the PDF.
- Run the three vetted PDFs through the real pipeline. Fix whatever the real documents expose in parse and segment.

### M4b — Citation parser and amendment detector
- `legal_core.citations`: Lark grammar for provision citations (section, subsection, clause, proviso, rule, schedule entry). The regex version stays as fallback until the Lark tests pass on the corpus.
- Worker stage `ingest.amend_detect` (after `apply_metadata`, for notifications): splitter, then Lark patterns for insert, substitute, omit and "for X read Y", then target resolution (unresolved stays `needs_info`), then a verbatim substring check. Writes `amendments` with `review_status=proposed`.
- Opens `amendment` review tasks (priority 1; `dry_run_ok=false` proposals first).

### M4c — Apply, consolidate, view
- Dry-run applier producing `dry_run_diff`.
- API `amendment` approval branch in `decide_task`: set reviewer and status, enqueue consolidation, write audit. Not-yet-in-force amendments are stored as approved with no version change. Ordering is `effective_from`, then issue date, then document ID.
- Consolidation worker: split the open interval at E, close old rows via `rec_to`, insert replacements in one transaction (respecting `pv_no_overlap`), write `consolidation_runs`, bump `corpus_versions`, write `links` and `document_status_history`.
- Nightly full-replay check and the manual-correction path (`origin=manual_correction`).
- Point-in-time API, version timeline, text diff.
- Web: `amendment-section.tsx` with the diff pane, plus the timeline view.
- Reviewer edits keep the original in `review_tasks.resolution` (no new `amendments` column).

### M4d — Rates and Rules back-fill
- `hsn_sac_codes` and `hsn_sac_rates` loading and review, starting from the goods rate notification. Services are added when the user supplies them.
- Rules back-fill: replay the supplied post-2019 amending notifications in chronological order (effective_from, then issue date, then document ID), with a report of detected, resolved, needs_info and rejected counts. No Act back-fill.

## Out of scope

Expert review of DRAFT config (courts, aliases, case patterns), query set (M5), fixture set (M7), GCP and Debian deployment, search and Q&A features.

## Verification

- `ruff check . && ruff format --check . && mypy`
- `pytest -q -m "not integration"`, and `DATABASE_URL=... pytest -q -m integration` for migration, provision build, consolidation and no-overlap tests (needs the HANDOFF Postgres setup).
- Web: `npm run lint && npm run typecheck && npm test && npm run build`, plus Playwright e2e for the amendment view.
- Acceptance on real documents: the three vetted baselines load with a reviewable provision tree. The sample notification yields proposals whose targets resolve, and approving them yields a correct point-in-time diff.
- Synthetic data only in committed fixtures. The vetted PDFs and any back-fill PDFs stay outside the repo.

## Environment constraint

This Windows machine has no Postgres or Tesseract. Integration tests and OCR need the HANDOFF container setup (a Linux environment). Until then, the unit tests, lint and type checks, and the web checks run locally. Integration verification would run where Postgres is available.

## Delegation

`explorer` (Sonnet) for survey and tracing. `implementer` (Haiku) for coding, given exact specs and separate file ownership per slice. Planning, review and final checks stay in the main session.

## Review changes / Known gaps

(To be filled in at the end of each slice.)
