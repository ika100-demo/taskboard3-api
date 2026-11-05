# Design — 002 Store tasks in Postgres instead of memory

The task contract of spec 001 (routes, models, validation, `422` format) is unchanged; `models.py` and `api.py` are not touched. What changes is the store behind `get_task_store`, the readiness probe, and two error handlers.

## Decisions

- **psycopg 3, plain SQL, one connection per request, no pool**; the app creates its table itself. Reasons and consequences: [ADR-001](../../adr/001-postgres-access-psycopg.md). This makes recovery after an outage immediate and needs no restart (AC-002.12, AC-002.13).
- **A new `db.py` module owns every database concern**: the URL, the timeouts, the schema, the mapping of driver errors onto `DatabaseUnavailable`. The store only runs its two statements; `main.py` only maps the exception to `503`.
- **An app factory, `create_app(database)`**, so tests can run two "instances", a "restarted" instance, an instance without a database or one pointing at a dead port in one process, each with its own `Database`. The module-level `app = create_app()` (what uvicorn runs) uses `Database.from_env()`, which reads `DATABASE_URL` at **each connection attempt**, not at import: the API starts without it (AC-002.13), and the test session can set it after `taskboard3_api.main` was imported.
- **Validation still runs before the database is touched.** `get_task_store` only builds a `TaskStore` around the app's `Database`; nothing connects until `add`/`list` runs inside the handler. FastAPI rejects an invalid body with `422` before the handler, so `422` wins over `503` (AC-002.11).
- **`TaskStore` keeps its name and its two methods** (`add`, `list`), now backed by Postgres; it takes a `Database`. The in-memory implementation is removed (no fallback store: an unreachable database must give `503`, never a silently empty list).
- **`due_date` is stored as `date`** and returned as `date.isoformat()`, which gives the same `YYYY-MM-DD` string the client sent (the validator already guarantees a four-digit year and a real date).
- **No retries inside a request** (spec non-goal): a failed connect or statement is a `503` at once.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard3_api/db.py` | `Database` (URL source, connect with timeouts, schema bootstrap, async `ping`), `DatabaseUnavailable` | new |
| `src/taskboard3_api/tasks/store.py` | `TaskStore(database)` with `add`/`list` in SQL; `get_task_store(request)` | changed (rewritten) |
| `src/taskboard3_api/tasks/__init__.py` | re-exports, docstring | changed |
| `src/taskboard3_api/main.py` | `create_app(database)`, `/ready` with the database ping, `503` and `500` JSON handlers; `app = create_app()` | changed |
| `pyproject.toml`, `uv.lock` | dependency `psycopg[binary]>=3.2` | changed |
| `devbox.json` | package `postgresql@16` (binaries for the test cluster) | changed |
| `docs/env-vars.md` | `DATABASE_URL` | changed |

### Interfaces

```python
# db.py
CONNECT_TIMEOUT_S = 2          # connect (libpq connect_timeout)
STATEMENT_TIMEOUT_MS = 5000    # per session: options="-c statement_timeout=5000"
READY_TIMEOUT_S = 1.0          # asyncio deadline around the whole ping
DATABASE_URL_ENV = "DATABASE_URL"

class DatabaseUnavailable(Exception):
    """No URL configured, connect failed/timed out, or a statement failed with an operational error."""

class Database:
    def __init__(self, url_source: Callable[[], str | None]) -> None: ...
    @classmethod
    def from_env(cls) -> "Database": ...            # url_source reads os.environ.get("DATABASE_URL") on every call
    @classmethod
    def from_url(cls, url: str | None) -> "Database": ...   # fixed URL; None or "" = not configured

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection[TupleRow]]: ...
        # 1. url = url_source(); None/"" (after strip) -> raise DatabaseUnavailable
        # 2. psycopg.connect(url, connect_timeout=2, options="-c statement_timeout=5000",
        #                    client_encoding="utf8")
        # 3. if not self._schema_ready (per instance, guarded by a threading.Lock):
        #        in its own committed transaction: SELECT pg_advisory_xact_lock(<module constant>);
        #        CREATE TABLE IF NOT EXISTS tasks (...)   -- see Data
        #        self._schema_ready = True
        # 4. yield the connection inside `with conn:` (commit on success, rollback on any exception),
        #    close the connection afterwards in every case
        # psycopg.OperationalError (includes QueryCanceled from statement_timeout and every
        # connection failure), psycopg.InterfaceError, and psycopg.ProgrammingError raised while
        # parsing the URL -> raise DatabaseUnavailable(...) from exc
        # Never log or put the URL (it holds the password) into the exception message.

    async def ping(self) -> bool: ...
        # asyncio.wait_for(_ping(), READY_TIMEOUT_S); _ping: no URL -> False;
        # psycopg.AsyncConnection.connect(url, connect_timeout=2, options="-c statement_timeout=1000"),
        # "SELECT 1", close. Any exception or TimeoutError -> False. Never raises.

# tasks/store.py
class TaskStore:
    def __init__(self, database: Database) -> None: ...
    def add(self, data: TaskCreate) -> Task: ...
        # id = str(uuid.uuid4())
        # INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s) RETURNING id, title, due_date
        # due_date param: date.fromisoformat(data.due_date) or None; result built from RETURNING
    def list(self) -> list[Task]: ...
        # SELECT id, title, due_date FROM tasks ORDER BY seq
    # both raise DatabaseUnavailable (from Database.transaction); they never return partial results

def get_task_store(request: Request) -> TaskStore: ...   # TaskStore(request.app.state.database); no I/O

# main.py
def create_app(database: Database | None = None) -> FastAPI: ...
    # database defaults to Database.from_env(); stored as app.state.database
    # adds MetricsMiddleware, the tasks router, /health, /ready, /ping, /metrics,
    # exception handlers for DatabaseUnavailable (503) and Exception (500)
app = create_app()
```

`configure_logging` and `configure_tracing` stay at module level in `main.py` (once per process, not per `create_app` call). `taskboard3_api.tasks` re-exports `router`, `Task`, `TaskCreate`, `TaskStore`, `get_task_store`; `Database` and `DatabaseUnavailable` are imported from `taskboard3_api.db`.

The `DatabaseUnavailable` handler is registered for that class (Starlette's inner exception middleware, so `MetricsMiddleware` records a `503`); the `Exception` handler is the server-error handler (outermost), so `MetricsMiddleware` still sees the exception and counts it in `application_errors_total` as `tests/test_metrics.py` expects.

## Contract

Unchanged from spec 001 (its design.md, section Contract) for valid and invalid requests: `POST /tasks` → `201` Task or `422` FastAPI validation body; `GET /tasks` → `200` array in creation order. "No task has been created" (AC-001.4) means the `tasks` table holds no row. The generated OpenAPI document for `/tasks` is unchanged (AC-002.4).

New:

| Request | Database state | Response |
|---|---|---|
| `GET /tasks`, valid `POST /tasks` | not configured (`DATABASE_URL` unset/empty), refused, unreachable, connect > 2 s, statement > 5 s, any `OperationalError` | `503` `{"detail": "database unavailable"}`, `Content-Type: application/json`, within 5 s; a failed `POST` stored nothing (transaction rolled back or never opened) (AC-002.8, AC-002.9, AC-002.10, AC-002.13) |
| invalid `POST /tasks` | any | `422` exactly as spec 001, the database is not contacted (AC-002.11) |
| `GET /ready` | `SELECT 1` succeeds within 1 s | `200` `{"status": "ready"}` (AC-002.14) |
| `GET /ready` | not configured, unreachable, or no answer within 1 s | `503` `{"status": "not ready"}`, within 2 s (AC-002.13, AC-002.15) |
| `GET /health` | any | `200` `{"status": "ok"}`, never touches the database (AC-002.13, AC-002.16) |
| any route | unexpected exception (not a database error) | `500` `{"detail": "internal server error"}`, no stack trace in the body; the exception is logged |

Every request after an outage connects anew; the first request after the database is back succeeds (AC-002.12, AC-002.13, AC-002.15). The process starts and serves `/health` whether or not a database is configured or reachable (AC-002.13).

Logging: the `503` handler logs one structured `warning` event `database_unavailable` with the route and the exception class (`error_type`), never the URL or password.

## Data

Table `tasks`, created on the first successful connection of each `Database` instance:

```sql
CREATE TABLE IF NOT EXISTS tasks (
    seq      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id       text         NOT NULL UNIQUE,
    title    varchar(200) NOT NULL,
    due_date date         NULL
);
```

`varchar(200)` counts characters, so 200 non-ASCII characters fit (AC-002.5); the connection uses `client_encoding=utf8`. The list order is `ORDER BY seq`: identity values follow the order of sequential requests across instances (AC-002.1, AC-002.3). `seq` is never exposed. No migration of in-memory tasks (non-goal).

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | _(unset: the API starts, `/ready` and `/tasks` answer `503`)_ | libpq URL, e.g. `postgresql://user:pass@host:5432/db`; set by the system's gitops `uses: postgres`. When it is unset or empty the app does not connect at all (no fallback to `PG*`); libpq may still fill parts the URL leaves out from `PG*`. |

## Testing notes (for the testers; the files are theirs)

- **Postgres in tests.** `devbox.json` provides `initdb` and `pg_ctl` (package `postgresql@16`). `tests/conftest.py` gets a **session** fixture `postgres_url` that:
  - fails (not skips) with "initdb/pg_ctl not on PATH: run the tests through `devbox run test`" when `shutil.which` finds either binary missing;
  - picks a free port (bind `127.0.0.1:0`, read the port, close);
  - `initdb -D <tmp>/data -U postgres -A trust -E UTF8 --no-locale`;
  - `pg_ctl -D <tmp>/data -l <tmp>/log -w -o "-p <port> -c listen_addresses=127.0.0.1 -c unix_socket_directories=''" start` (TCP only: avoids the macOS socket path length limit and the `PGHOST`/`PGDATA` the devbox postgresql plugin may export);
  - yields `postgresql://postgres@127.0.0.1:<port>/postgres`, sets `os.environ["DATABASE_URL"]` to it for the session (the module-level `app` reads it lazily), and runs `pg_ctl -D … -m immediate -w stop` at teardown, restoring the previous `DATABASE_URL`.
  - It is **not autouse**: only in-process fixtures request it, so `devbox run smoke` never starts a cluster. The existing `client` fixture must depend on it (`test_health.py`'s `/ready` test then sees a reachable database).
- **Isolation:** a function fixture truncates (`TRUNCATE tasks RESTART IDENTITY` when the table exists) before each task test; tests may open their own `psycopg` connection to the same URL to inspect or prepare the table.
- **Instances:** `create_app(Database.from_url(url))` per instance; two of them = two instances (AC-002.2, AC-002.3); dropping one and creating a new one = a restart (AC-002.1). AC-002.6: `DROP TABLE IF EXISTS tasks`, then a **fresh** `create_app(...)` (the schema flag is per `Database`).
- **Spec 001 tests** (`tests/test_tasks.py`) currently override `get_task_store` with `TaskStore()`; that constructor no longer exists. Per AC-002.4 they run against the database: their `api` fixture becomes `TestClient(create_app(Database.from_url(postgres_url)))` on a truncated table, assertions unchanged.
- **Database down:** a closed port (bind to `127.0.0.1:0`, close, use the port) gives an immediate refusal (AC-002.8, AC-002.9, AC-002.11, AC-002.16); `Database.from_url(None)` or `DATABASE_URL` unset gives "not configured" (AC-002.13). "Does not answer within 1 s" (AC-002.15): a socket that `listen()`s but never accepts or replies. Recovery (AC-002.12, AC-002.13, AC-002.15): a second, function-scoped cluster helper with `stop()`/`start()` on its own port (or start a cluster on the port the app already points to), so the session cluster stays up for other tests.
- **Slow statement (AC-002.10):** in a separate connection `BEGIN; LOCK TABLE tasks IN ACCESS EXCLUSIVE MODE;`, then `POST /tasks` (and `GET /tasks`) block on the lock until `statement_timeout` cancels them → `503` after about 5 s; release the lock, `GET /tasks` does not contain that title. Use an app whose schema is already bootstrapped (one successful request first), so the bootstrap does not wait on the lock.
- **Smoke:** keep the existing read-only `GET /tasks` smoke check (AC-002.7) and the writing one; add a read-only smoke check `GET /ready` → `200 {"status": "ready"}` (AC-002.14). All through `SMOKE_BASE_URL` only.

## Risks

- `/platform:update` rewrites the template's `devbox.json` recipes; the `packages` entry `postgresql@16` must survive it. If it is lost, the `postgres_url` fixture fails with a clear message (no silent skip).
- Connection per request: fine at the current load; a pool is a `db.py`-only change later (ADR-001).
- A `DROP TABLE` behind a running process is not repaired (the schema flag is per process); out of scope (no schema management beyond create-if-missing).
- `localhost` in a URL resolves to two addresses, each with its own 2 s connect timeout; the cluster URL from gitops uses a service hostname (one address), tests use `127.0.0.1`.
