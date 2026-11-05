# ADR-001: Postgres access with psycopg 3, one connection per request, schema created by the app

## Status

Accepted (spec 002, 2026-11-05).

## Context

Spec 002 moves tasks from process memory into the system's Postgres (`DATABASE_URL`, wired by the gitops `uses: postgres` operation). The contract fixes hard limits: connect within 2 s, statements within 5 s, `/ready` answers within 2 s with a 1 s `SELECT 1`, a `503 {"detail": "database unavailable"}` for any database failure, and recovery **without a restart** as soon as the database is back. The API must also start when no database is configured or reachable. Only one table exists; schema versioning is a non-goal. Tests must run against a real Postgres that devbox provides (no Docker, no tool outside devbox).

## Decision

- **Driver: psycopg 3 (`psycopg[binary]`), plain SQL, no ORM.** The binary wheel bundles libpq, so the slim runtime image needs no system packages; psycopg is typed (mypy strict) and maps statement timeouts and connection failures onto `psycopg.OperationalError`, which we translate into one domain exception (`DatabaseUnavailable`) and one `503`.
- **One short-lived connection per request, no pool** (`connect_timeout=2`, `statement_timeout=5000` per session). A failed connect costs nothing afterwards: the next request simply connects again, so recovery after an outage is immediate and deterministic, with no background reconnect thread and no backoff that could delay it (AC-002.12, AC-002.13). At the service's load (a handful of requests per second in dev) the connect cost of a few ms is irrelevant. Introducing `psycopg_pool` later is a change inside `db.py` only.
- **Readiness uses the async driver under `asyncio.wait_for(…, 1.0)`**, because libpq and psycopg clamp `connect_timeout` to at least 2 s; only an asyncio deadline gives the 1 s bound of the contract.
- **The app owns its schema**: `CREATE TABLE IF NOT EXISTS` under a transaction-level advisory lock on the first successful connection of each process, so concurrent instances cannot race. No migration tool until a spec needs a second schema change.
- **`DATABASE_URL` is the only connection setting the app reads.** When it is unset or empty the app does not fall back to `PG*` variables; it behaves as if the database were unreachable.
- **Tests run a throwaway Postgres cluster** from the devbox `postgresql` package (`initdb`/`pg_ctl` on a free port in a temp dir), started by a pytest session fixture.

## Consequences

**Positive:** no new infrastructure in the repo; fully predictable failure and recovery behaviour; the same database engine in tests and in the cluster; one module (`db.py`) holds every database concern.

**Negative:** each request pays a TCP + auth handshake; if load grows, add a pool inside `db.py` (keeping the same timeouts and the per-request retry). `devbox.json` gains a package (`postgresql`), which a `/platform:update` must keep; if an update drops it, `devbox run test` fails loudly at the fixture, not silently. A future schema change needs a migration decision (new ADR).
