# Verification — 002 Store tasks in Postgres instead of memory, with 503 and not-ready while the database is down

**Result:** pass
**Commit:** 18804a3 · **Base:** 6d09665 · **Trace:** 16/16 criteria named by tests (smoke: AC-002.7, AC-002.14)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-002.1 | met | `tests/test_tasks_postgres.py::test_tasks_survive_restart` | `src/taskboard3_api/tasks/store.py:20`, `src/taskboard3_api/tasks/store.py:40` (`ORDER BY seq`) | A new `create_app` against the same database returns `200` and exactly the three create responses, in order (one has a `due_date`). |
| AC-002.2 | met | `tests/test_tasks_postgres.py::test_second_instance_sees_task` | `src/taskboard3_api/tasks/store.py:47`, `src/taskboard3_api/main.py:55` | The whole create response (id, title, due_date) is in the second instance's list. |
| AC-002.3 | met | `tests/test_tasks_postgres.py::test_order_across_instances` | `src/taskboard3_api/db.py:22` (identity `seq`), `src/taskboard3_api/tasks/store.py:40` | Both instances list `[a, b]`; the ids differ. |
| AC-002.4 | met | `tests/test_tasks.py` (all AC-001.1 to AC-001.13 tests, now on `create_app(Database.from_url(clean_tasks))`, assertions unchanged), `tests/test_tasks_postgres.py::test_invalid_input_creates_no_row` | `src/taskboard3_api/tasks/store.py:20-44`; `api.py`/`models.py` untouched | The diff from base only changes the fixture and adds `AC-002.4` tags. AC-001.4 against the database: an invalid POST leaves `count(*) = 0` in `tasks`. The OpenAPI test still passes. |
| AC-002.5 | met | `tests/test_tasks_postgres.py::test_200_non_ascii_characters` | `src/taskboard3_api/db.py:22` (`varchar(200)`), `src/taskboard3_api/db.py:82` (`client_encoding="utf8"`) | `"ä"*200` padded with spaces is trimmed. The create response and the list both carry the title and `2026-12-31` unchanged. |
| AC-002.6 | met | `tests/test_tasks_postgres.py::test_table_created_on_first_connect` | `src/taskboard3_api/db.py:60-74` | After `DROP TABLE`, a fresh app gets `GET` `200 []`, then `POST` `201`. |
| AC-002.7 (smoke) | met | `tests/test_smoke_postgres.py::test_ac_002_7_list_tasks_returns_array` | `src/taskboard3_api/tasks/store.py:37` | Read-only smoke test against `SMOKE_BASE_URL`: `200` and a list. Runs after deploy to dev. |
| AC-002.8 | met | `tests/test_tasks_postgres.py::test_get_tasks_503_when_db_down` | `src/taskboard3_api/db.py:93-99`, `src/taskboard3_api/main.py:31-38`, `src/taskboard3_api/main.py:58` | Refused port: `503` with the exact body in under 5 s. |
| AC-002.9 | met | `tests/test_tasks_postgres.py::test_post_503_when_db_down_stores_nothing` | `src/taskboard3_api/db.py:93-104`, `src/taskboard3_api/main.py:38` | Cluster stopped: `503` with the exact body in under 5 s. After a restart the list has no "lost". |
| AC-002.10 | met | `tests/test_tasks_postgres.py::test_slow_statement_gives_503`, `::test_slow_statement_task_not_stored` | `src/taskboard3_api/db.py:81` (`statement_timeout=5000`), `src/taskboard3_api/db.py:101-104` (rollback via `with conn`, `QueryCanceled` is an `OperationalError`) | With an ACCESS EXCLUSIVE lock held, POST answers `503` after 4 to 9 s and GET answers `503`. After the lock is released, "slow-two" is not listed. |
| AC-002.11 | met | `tests/test_tasks_postgres.py::test_invalid_input_is_422_not_503` | `src/taskboard3_api/tasks/store.py:47-49` (no I/O in the dependency) | Dead database: an empty title gets `422` with `loc` naming `title`. |
| AC-002.12 | met | `tests/test_tasks_postgres.py::test_recovery_without_restart` | `src/taskboard3_api/db.py:86-107` (connection per request, no cached failure) | `503` while down. Same app afterwards: `200` with the earlier tasks in order, and POST `201`. |
| AC-002.13 | met | `tests/test_tasks_postgres.py::test_starts_without_database_configured`, `::test_starts_with_unreachable_database` | `src/taskboard3_api/db.py:54-57`, `src/taskboard3_api/db.py:116-119`, `src/taskboard3_api/main.py:52-86` (no startup connect) | Unset and unreachable cases both give `/health` `200 ok`, `/ready` `503 not ready` and `/tasks` `503` with the body. Both recover without a restart. |
| AC-002.14 (smoke) | met | `tests/test_tasks_postgres.py::test_ready_when_database_reachable`, `tests/test_health.py::test_ready_returns_ready`, `tests/test_smoke_postgres.py::test_ac_002_14_ready_reports_ready` | `src/taskboard3_api/main.py:66-71`, `src/taskboard3_api/db.py:109-126` | |
| AC-002.15 | met | `tests/test_tasks_postgres.py::test_ready_503_when_unreachable_then_recovers`, `::test_ready_503_on_refused_port` | `src/taskboard3_api/db.py:112` (`wait_for` 1 s), `src/taskboard3_api/main.py:71` | A socket that listens but never answers gives `503 not ready` in under 2 s, and the next call after the URL becomes reachable gives `200 ready`. A refused port also gives `503` in under 2 s. |
| AC-002.16 | met | `tests/test_tasks_postgres.py::test_health_ok_when_db_down` | `src/taskboard3_api/main.py:61-64` | `/health` never touches the database. |

## Non-goals

- No migration of in-memory tasks, and no fallback store: the in-memory store was removed (`store.py`). ✔
- The task contract is unchanged: `tasks/api.py` and `tasks/models.py` are not in the diff, and no new routes, fields or pagination. ✔
- No retries or queueing: `transaction()` makes one attempt and fails with `DatabaseUnavailable` (`db.py:86-107`). ✔
- No schema versioning: only `CREATE TABLE IF NOT EXISTS` (`db.py:21-28`). ✔
- No provisioning, backups, staging or prod wiring. ✔
- Template-owned files: `devbox.json` only gains `postgresql@16` in `packages`, and no recipe in `shell.scripts` changed. ✔

## Deviations from the plan

- `devbox.json` and `devbox.lock` were changed in the testers' red commit `6771a59`, not in t1. `devbox.lock` is in no task's `files`. Acceptable: the lock is generated together with t1's `devbox.json` change, and the fixture needs `initdb`/`pg_ctl`.
- `docs/adr/001-postgres-access-psycopg.md` and the spec docs are in no task's `files`. Acceptable: these are planning artifacts linked from `plan.md`.
- `tests/*` are in no task's `files`, as the plan intends (written by the testers). Since the red commit there have been lint-only changes plus the approved `table_lock` teardown (`9fb2772`, ends the lock-holding backend). No assertion changed.
- `store.py:29-30` raises `RuntimeError` when `INSERT ... RETURNING` yields no row; it replaced an `assert` because of bandit B101. Acceptable: the path cannot be reached in practice, and if it were, the `500` handler would answer.
- All tasks t1 to t3 are `done: true`.

## Contract

Matches `design.md`:
- Timeouts: connect 2 s, `statement_timeout` 5000 ms, ready deadline 1 s with a 1000 ms statement timeout.
- `503` body `{"detail": "database unavailable"}`, logged as `database_unavailable` with `route` and `error_type` and without the URL (`main.py:31-38`).
- `500` body `{"detail": "internal server error"}` (`main.py:41-49`).
- `/ready` returns `200 {"status": "ready"}` or `503 {"status": "not ready"}`.
- `create_app(database)` and the module-level `app`.
- `Database.from_env()` reads `DATABASE_URL` lazily.
- The table layout and `ORDER BY seq`.
- `DATABASE_URL` is documented in `docs/env-vars.md`.

The `500` handler has no acceptance test; no criterion requires one. ✔
