# M1 plan: Core data and auth

Status: **approved by the user on 2026-10-08 (frozen)** · Milestone: TSD 13.2 M1 · Workstreams A, G

## Goal

Exit criteria (TSD 13.2): "Schema and migrations (section 4), local auth, roles, audit log."

When M1 is done:

1. A fresh database upgraded to `head` holds every MVP table from TSD section 4, with its constraints and indexes.
2. A user can log in with email and password and receive a JWT. Roles are loaded from the database on every request.
3. Login, logout, failed logins, user and role changes, and audit queries are written to a hash-chained, append-only `audit_log`.
4. A platform admin can manage users and roles, and query the audit log, through the API.

## Scope

### In

- Migrations for all **MVP** tables in TSD 4.2 to 4.9 (list below).
- Local auth: argon2 password hashing, HS256 session JWT, login rate limit.
- Roles and a permissions map in code (TSD 9.2).
- Audit log with hash chain, an append-only trigger and a chain verifier (TSD 9.6).
- Endpoints:
  - `POST /v1/auth/login`
  - `POST /v1/auth/logout`
  - `GET /v1/me`
  - `GET, POST /v1/admin/users`
  - `PATCH /v1/admin/users/{id}`
  - `GET /v1/admin/audit`
- A CLI to create the first admin user and to verify the audit chain.

### Out (deferred, with the reason)

| Item | Why |
| --- | --- |
| P2 tables: `conversations`, `judgement_summaries`, `chunk_embeddings`, `answers*`, `feedback`, `llm_usage` | TSD marks them Deferred (P2). |
| Production-only tables: `consents`, `os_index_state` | TSD marks them production profile. |
| RLS policies and the `app_rw`, `ingest_rw` and other database roles | TSD 9.1 puts them in P2 or production. The POC has no tenants. |
| Web login page | Belongs to the web workstream (WS-F). M1 delivers the API only. |
| MFA, Cognito, refresh tokens | P-3. |
| Server-side token revocation | POC uses short-lived JWTs. Disabling a user takes effect on their next request, because user status and roles are re-read from the database each time. |

## Design decisions

1. **IDs: UUIDv7.** Migration 0003 defines a SQL function `uuid_generate_v7()` and uses it as the default ID on every new table. Postgres 16 has no built-in UUIDv7. A database default also covers the worker's raw-SQL inserts. Existing tables keep their current IDs.
2. **Migrations stay hand-written** (repo convention). SQLAlchemy ORM models are added only for the tables the API uses in M1: `users`, `roles`, `user_roles`, `audit_log`. Later milestones add models as they need them.
3. **`tenants` table is created now.** It is small, and it lets every `tenant_id` column have a foreign key, so no table has to be altered later. `tenant_id` stays nullable and unused in the POC.
4. **Enums use CHECK constraints**, not Postgres enum types. They are easier to change in later migrations, and `job_queue` already uses them.
5. **Audit hash chain.**
   - Fields hashed: `row_hash = sha256(prev_hash || canonical_json(row fields))`. IPs are normalised with `ipaddress` before hashing and storing. `detail` holds only str, int, bool, null, list and dict values, so the JSONB round trip keeps hashes stable.
   - Ordering: the insert takes `pg_advisory_xact_lock` to keep the chain in order when requests run at the same time.
   - Timing: each audit row is written in the same transaction as the action it records.
   - Append-only: a trigger rejects UPDATE, DELETE and TRUNCATE on `audit_log`.
   - Verification: `verify_chain()` re-computes and checks the whole chain.
6. **Auth.**
   - Libraries: `argon2-cffi` and `PyJWT`.
   - Settings: `JWT_SECRET` is required with at least 32 characters. Token lifetime defaults to 8 hours (`JWT_TTL_MINUTES`).
   - Token: a bearer token in the `Authorization` header. The token carries only `sub`, `jti`, `iat` and `exp`. Roles are never read from it (TSD 8.1).
   - Login rate limit: in memory, 5 failures per email and IP in 15 minutes. That is enough for the POC's single API process.
   - Failed logins return one generic error, so the response doesn't reveal whether an email exists.
7. **Permissions** live in one map in `app/auth/permissions.py` (`role -> set of actions`). Routes check them through `require_permission("users.manage")`-style dependencies.
8. **Seeded roles.** All seven role codes from 4.2 are seeded. The POC uses three: `platform_admin`, `platform_content_editor` and `professional`.

## Migrations

| Revision | Tables |
| --- | --- |
| 0003_identity | `uuid_generate_v7()`, `tenants`, `users`, `roles` (seeded), `user_roles`, `audit_log` (append-only trigger), `matters`, `matter_members`, `topics`, `matter_topics`, `user_topic_follows`, `digest_prefs`, `saved_searches`, `saved_items`, `exports` |
| 0004_documents | `sources`, `documents`, `document_sources`, `document_versions`, `document_status_history`, `blocks`, `page_extractions`, `page_texts`, `notifications`, `circulars`, `judgements`, `judgement_treatments`, `council_items`, `document_topics`, `numbering_checks`, `source_coverage`, `synonym_terms`, `feed_items` |
| 0005_legal_structure | `instruments`, `provisions`, `provision_versions` (GiST overlap exclusion), `provision_topics`, `amendments`, `consolidation_runs`, `links`, `hsn_sac_codes`, `hsn_sac_rates` (overlap exclusion), `chunks` |
| 0006_operations | `review_tasks`, `ingestion_jobs` |

Each migration has a working `downgrade()`.

The indexes are those listed in TSD 4.5 and 4.11:
- GiST exclusion constraints
- `(provision_id, valid_from)`
- `chunks (tenant_id, is_current, doc_type)`
- trigram GIN on `documents.title` and `number`
- GIN on `chunks.tsv` and `page_texts.tsv`
- the `links` indexes

**Gaps in TSD section 4 that I will fill this way:**
- `hsn_sac_rates.condition_key` is used in the exclusion constraint but not listed as a column. I'll add it as `text NOT NULL DEFAULT ''`.
- `topic_ids` will be `uuid[]`.

## Files

- `apps/api/alembic/versions/0003_identity.py` to `0006_operations.py` (new)
- `apps/api/app/models.py`: ORM models for the M1 tables (new)
- `apps/api/app/auth/`: `passwords.py`, `tokens.py`, `permissions.py`, `ratelimit.py`, `deps.py` (new)
- `apps/api/app/audit.py`: write, hash and verify the audit chain (new)
- `apps/api/app/routers/`: `auth.py`, `admin_users.py`, `admin_audit.py` (new), registered in `main.py`
- `apps/api/app/cli.py`: `create-user` and `verify-audit` (new)
- `apps/api/app/settings.py`: add `jwt_secret`, `jwt_ttl_minutes` and the rate-limit settings
- `apps/api/pyproject.toml`, `requirements-dev.txt`: add `argon2-cffi`, `pyjwt`
- `.env.example`, `README.md`: document the bootstrap admin command
- `apps/api/tests/`: unit and integration tests (below)

## Verification

- **Unit tests** (no database):
  - password hash round trip
  - JWT issue and verify: expiry, bad signature, missing claims
  - permissions map
  - rate limiter
  - hash function is deterministic and detects changes
  - endpoints with dependency overrides: 401, 403, success paths
  - offline-SQL render of the new migrations
- **Integration tests** (`-m integration`, real Postgres 16):
  - upgrade to head, then downgrade to base, then upgrade again
  - the `provision_versions` overlap exclusion rejects overlapping current rows
  - the audit trigger blocks UPDATE and DELETE
  - end to end: create user via CLI, log in, call `/v1/me`, call admin endpoints, query audit, verify chain
  - a tampered audit row is detected by `verify_chain()`
  - a disabled user is rejected on their next request
- **Repo checks:** ruff, ruff format, mypy strict and the full pytest suite.
- **Where it runs:** this session has Postgres 16, so the integration tests run here, not only in CI.

## Separate issue found (not in this plan)

CI only runs on pushes and PRs to `main` and `develop`, and the repo has neither branch. CI has therefore never run. Decide separately how to fix this: create `main`, or widen the triggers.
