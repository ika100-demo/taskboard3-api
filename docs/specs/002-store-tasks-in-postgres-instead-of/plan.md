---
spec_id: 002-store-tasks-in-postgres-instead-of
shape: service-python
spec_hash: ecbbab1a27ef
summary: Postgres-backed TaskStore via psycopg 3 (connection per request, table created on first connect), 503 on database failure, /ready pings the database
tasks:
  - id: t1
    title: Add the psycopg dependency, the devbox postgresql package and the db module
    files: [src/taskboard3_api/db.py, pyproject.toml, uv.lock, devbox.json, docs/env-vars.md]
    covers: [AC-002.6, AC-002.8, AC-002.9, AC-002.10, AC-002.13, AC-002.15]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Replace the in-memory TaskStore with the Postgres store
    files: [src/taskboard3_api/tasks/store.py, src/taskboard3_api/tasks/__init__.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7, AC-002.9, AC-002.10, AC-002.11, AC-002.12]
    parallel_safe: true
    depends_on: [t1]
    done: true
  - id: t3
    title: App factory, database readiness probe and 503/500 JSON handlers
    files: [src/taskboard3_api/main.py]
    covers: [AC-002.8, AC-002.9, AC-002.10, AC-002.12, AC-002.13, AC-002.14, AC-002.15, AC-002.16]
    parallel_safe: true
    depends_on: [t1]
    done: true
---

# Plan — 002 Store tasks in Postgres instead of memory

Design and contract: [design.md](design.md). Decision record: [ADR-001](../../adr/001-postgres-access-psycopg.md).

Levels: t1 → t2, t3 (t2 and t3 touch disjoint files and only share `db.py` from t1). The acceptance tests, `tests/conftest.py` (the throwaway Postgres fixture) and the smoke tests are written by the testers before coding and are not in any task.

## t1 — Add the psycopg dependency, the devbox postgresql package and the db module

**Files:** src/taskboard3_api/db.py, pyproject.toml, uv.lock, devbox.json, docs/env-vars.md
**Covers:** AC-002.6, AC-002.8, AC-002.9, AC-002.10, AC-002.13, AC-002.15
**Goal:** every database concern in one module, `taskboard3_api.db`, exactly as in design.md's Interfaces, plus the tooling the tests need: the driver in the project and the Postgres binaries in devbox.

**Implementation notes:**
- `pyproject.toml`: add `"psycopg[binary]>=3.2"` to `dependencies`. Refresh `uv.lock` through devbox (the `init_hook` runs `uv sync --all-extras` on `devbox shell` / `devbox run`); never call `uv add` or `pip` directly. The Dockerfile runs `uv sync --locked`, so the lock must be committed.
- `devbox.json`: add `"postgresql@16"` to `packages` only; do not touch any recipe in `shell.scripts` (template-owned). Check that `devbox run -- which initdb pg_ctl` finds both.
- `db.py`: constants `CONNECT_TIMEOUT_S = 2`, `STATEMENT_TIMEOUT_MS = 5000`, `READY_TIMEOUT_S = 1.0`, `DATABASE_URL_ENV`; `class DatabaseUnavailable(Exception)`.
- `Database(url_source)`, `Database.from_env()` (reads `os.environ.get("DATABASE_URL")` on each call, never at import), `Database.from_url(url)`; `None` or blank URL means not configured → `DatabaseUnavailable` without any connect attempt (AC-002.13).
- `transaction()` context manager: `psycopg.connect(url, connect_timeout=2, options="-c statement_timeout=5000", client_encoding="utf8")`, `with conn:` (commit on success, rollback on error), always close. Wrap `psycopg.OperationalError` (covers `QueryCanceled` and connection failures), `psycopg.InterfaceError` and a URL-parsing `psycopg.ProgrammingError` into `DatabaseUnavailable ... from exc` (AC-002.8, AC-002.9, AC-002.10).
- Schema bootstrap once per `Database` instance (flag + `threading.Lock`), in its own committed transaction before the caller's: `SELECT pg_advisory_xact_lock(<module constant>)`, then the `CREATE TABLE IF NOT EXISTS tasks (...)` from design.md's Data (AC-002.6). If the bootstrap fails, the flag stays unset so the next request tries again.
- `async def ping() -> bool`: `asyncio.wait_for` with `READY_TIMEOUT_S` around `psycopg.AsyncConnection.connect(url, connect_timeout=2, options="-c statement_timeout=1000")` + `SELECT 1` + close; returns `False` on no URL, any exception or timeout; never raises (AC-002.15).
- Never put the URL into messages or logs (it carries the password).
- `docs/env-vars.md`: a "Database" section with `DATABASE_URL` as in design.md's Configuration.
- Full type hints and docstrings; `mypy --strict` and bandit clean (only static SQL strings, parameters through `%s`).

**Done when:** `devbox run quality` and `devbox run security` pass, `initdb`/`pg_ctl` are on the devbox PATH so the testers' `postgres_url` fixture starts a cluster; the HTTP acceptance tests turn green with t2 and t3.

## t2 — Replace the in-memory TaskStore with the Postgres store

**Files:** src/taskboard3_api/tasks/store.py, src/taskboard3_api/tasks/__init__.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7, AC-002.9, AC-002.10, AC-002.11, AC-002.12
**Goal:** `TaskStore` keeps its name and its `add`/`list` methods but persists in the `tasks` table, so tasks survive restarts and are shared between instances, with the spec 001 contract unchanged.

**Implementation notes:**
- Remove the in-memory list, the lock and the module-level `_store`.
- `TaskStore.__init__(self, database: Database)`.
- `add`: `id = str(uuid.uuid4())`; inside `database.transaction()` run `INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s) RETURNING id, title, due_date` with `due_date` as `datetime.date.fromisoformat(...)` or `None`; build the `Task` from the returned row, `due_date.isoformat()` or `None` (AC-002.1, AC-002.5). A failure rolls back, so nothing is stored (AC-002.9, AC-002.10).
- `list`: `SELECT id, title, due_date FROM tasks ORDER BY seq` → `list[Task]` (AC-002.1, AC-002.3, AC-002.4).
- Let `DatabaseUnavailable` propagate; no catching, no retry (spec non-goal).
- `get_task_store(request: fastapi.Request) -> TaskStore`: `TaskStore(request.app.state.database)`; no I/O here, so an invalid body still yields `422` before any database access (AC-002.11).
- `src/taskboard3_api/tasks/api.py` and `models.py` stay unchanged (the `StoreDep` annotation still resolves through `get_task_store`).
- `__init__.py`: same exports (`Task`, `TaskCreate`, `TaskStore`, `get_task_store`, `router`); docstring says "Postgres store" instead of "in-memory store".

**Done when:** with t3 merged, the acceptance tests for AC-002.1 to AC-002.6, AC-002.9 to AC-002.12 and the adapted spec 001 tests (`tests/test_tasks.py`) pass under `devbox run test`; `devbox run quality` is green. AC-002.7 is checked by the read-only smoke test after deploy.

## t3 — App factory, database readiness probe and 503/500 JSON handlers

**Files:** src/taskboard3_api/main.py
**Covers:** AC-002.8, AC-002.9, AC-002.10, AC-002.12, AC-002.13, AC-002.14, AC-002.15, AC-002.16
**Goal:** `create_app(database)` as in design.md, a `/ready` that reflects the database, and the new error bodies, while `/health`, `/ping` and `/metrics` keep behaving as before.

**Implementation notes:**
- Keep `configure_logging(...)` and the tracing setup at module level (once per process).
- `def create_app(database: Database | None = None) -> FastAPI`: `FastAPI(title="taskboard3-api", version=__version__)`, `app.state.database = database or Database.from_env()`, add `MetricsMiddleware`, include the tasks router, register `/health`, `/ready`, `/ping`, `/metrics` and the two handlers; end of module `app = create_app()` (uvicorn's `taskboard3_api.main:app` and the existing tests keep working).
- `/health`: unchanged, never touches the database (AC-002.16).
- `/ready`: `async def`; `await request.app.state.database.ping()` → `200 {"status": "ready"}` or `JSONResponse(status_code=503, content={"status": "not ready"})`; keep `response_model=HealthResponse` for the docs (AC-002.13, AC-002.14, AC-002.15).
- `app.add_exception_handler(DatabaseUnavailable, ...)` → `JSONResponse(503, {"detail": "database unavailable"})`, logs a structlog `warning` `database_unavailable` with `route` and `error_type`, no URL (AC-002.8, AC-002.9, AC-002.10, AC-002.13).
- `app.add_exception_handler(Exception, ...)` → `JSONResponse(500, {"detail": "internal server error"})`, logs the exception; being Starlette's server-error handler, the exception still passes through `MetricsMiddleware` (keeps `tests/test_metrics.py` green).
- No startup hook that connects: the process starts with or without a reachable database (AC-002.13); every request connects anew, so service resumes once the database is back (AC-002.12).

**Done when:** with t2 merged, the acceptance tests for AC-002.8, AC-002.9, AC-002.10, AC-002.12 to AC-002.16 pass, `tests/test_health.py`, `tests/test_metrics.py` and `tests/test_tracing.py` still pass, and `devbox run ci` is green. AC-002.14 is also checked by the read-only `/ready` smoke test after deploy.
