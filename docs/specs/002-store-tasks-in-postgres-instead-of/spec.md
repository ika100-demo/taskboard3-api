---
spec_id: 002-store-tasks-in-postgres-instead-of
title: Store tasks in Postgres instead of memory, with 503 and not-ready while the database is down
status: approved
priority: P1
shape: service-python
parent: ika100-demo/taskboard3-gitops:001-tasks-in-postgres-seen-and-created-in
---

# 002 — Store tasks in Postgres instead of memory, with 503 and not-ready while the database is down

## Problem

The Task API can create and list tasks, but it keeps them in process memory. Every restart or redeploy (which happens on every merge to main in dev) deletes all tasks, and two running instances would each show a different list. The web app is still the starter page, so a person who is not using API tools has no way to see or add tasks. This spec makes tasks durable in a Postgres database that belongs to the system, and gives people a page in the web app where they can see the task list and add a task. The task contract of the API (fields, validation, order) stays as it is.

## System context

Slice of the system plan `001-tasks-in-postgres-seen-and-created-in` in `ika100-demo/taskboard3-gitops` for `taskboard3-api` (service-python). The system criteria and the contract below are binding: every criterion of this spec implements one of them and names it: `(system AC-<NNN>.<n>)`.

### System criteria

- **AC-001.1** Given tasks A, B and C were created through `POST /tasks`, when the API is restarted or redeployed, then `GET /tasks` still returns A, B and C in creation order, each with the same `id`, `title` and `due_date` as its create response.
- **AC-001.2** Given the API runs as more than one instance in an environment, when a task is created through one instance, then `GET /tasks` answered by any instance includes that task.
- **AC-001.3** Given the database is in use, when clients call `POST /tasks` and `GET /tasks`, then requests, responses, validation errors and list order are exactly as in the API's spec 001 (title required, trimmed, 1 to 200 characters; optional `due_date` as `YYYY-MM-DD`, past dates accepted; `201` with `{id, title, due_date}`; `422` on invalid input; list in creation order).
- **AC-001.4** Given the database cannot be reached, when a client sends `POST /tasks` or `GET /tasks`, then the response is `503` with a JSON error body, no task is lost or half-created, and once the database is reachable again both requests work without restarting the API.
- **AC-001.5** Given the database cannot be reached, when the API's readiness endpoint is called, then it reports not ready; the health endpoint keeps reporting healthy.

### Contract

Between `taskboard3-web` (caller, server side only) and `taskboard3-api`, plus the API's own database layout and probes. Base URL in the cluster: `TASKS_API_URL=http://taskboard3-api` (no trailing slash). All bodies are JSON (`Content-Type: application/json`).

### Task object

```json
{"id": "3f2c9a8e-...", "title": "Buy milk", "due_date": "2026-12-31"}
```

| Field | Type | Notes |
|---|---|---|
| `id` | string, non-empty | Opaque. A UUID string today; the caller must not parse it. |
| `title` | string | Already trimmed, 1 to 200 characters. |
| `due_date` | string `YYYY-MM-DD` or `null` | A calendar date, no time and no time zone. Callers display it as is. |

No other fields. A caller ignores any extra field it does not know.

### `GET /tasks`

- `200` with a JSON array of Task objects, oldest first (creation order). `[]` when there are none. No pagination.
- `503` when the database is unavailable (see Errors).

### `POST /tasks`

Request body: `{"title": <string>, "due_date": <"YYYY-MM-DD" | null>}`. `due_date` may be omitted (same as `null`). The web app sends `null` when no date is picked, and sends the title as typed (the API trims it).

- `201` with the created Task object.
- `422` on invalid input (FastAPI's validation format, see Errors). The rules are unchanged from the API's spec 001: `title` is required, a string, trimmed, 1 to 200 characters; `due_date` is a valid calendar date in `YYYY-MM-DD` or `null`, and past dates are accepted.
- `503` when the database is unavailable. No task was stored.

### Probes of the API

- `GET /health`: `200 {"status": "ok"}` as long as the process runs. It never checks the database.
- `GET /ready`: `200 {"status": "ready"}` when `SELECT 1` succeeds within 1 s. Otherwise `503 {"status": "not ready"}`.

### Storage (API internal, listed so both sides know where the order comes from)

Table `tasks`, created by the API on startup or on the first successful connection (`CREATE TABLE IF NOT EXISTS`):

| Column | Type | |
|---|---|---|
| `seq` | `bigint generated always as identity` | Primary key. The list is `ORDER BY seq`. Never exposed. |
| `id` | `text not null unique` | The UUID returned as `id`. |
| `title` | `varchar(200) not null` | |
| `due_date` | `date null` | Serialized back as `YYYY-MM-DD`. |

Connection settings: `DATABASE_URL` (set by the gitops `uses: postgres` operation). Tasks that the running in-memory API holds are not migrated (a non-goal).

### Errors

- **`422`** (unchanged, FastAPI default): `{"detail": [{"type": "...", "loc": ["body", "title"], "msg": "...", "input": ...}, ...]}`. `loc` names the field (`title` or `due_date`).
- **`503`** (new): `{"detail": "database unavailable"}`. The API sends it for any database connection error, pool timeout or statement timeout on `/tasks`. Other unexpected server errors stay `500`, also with a JSON `{"detail": ...}` body and no stack trace.
- **How the web app treats responses:**
  - `GET /tasks`: only a `200` with a JSON array counts as success. Any other status (`503`, `500`, `404`, ...), a body that is not a JSON array, a refused connection or a timeout shows "Tasks could not be loaded. Please try again later." instead of the list. The page itself still returns `200`.
  - `POST /tasks`:
    - `201`: append the returned task and clear the form.
    - `422` whose `detail` has an entry with `"title"` in `loc`: show the title message that fits the trimmed input ("Please enter a title." when empty, otherwise "The title can be at most 200 characters."). Normally the client check catches these first.
    - Any other `422`, any other status, a body that is not a Task object, a refused connection or a timeout: show "The task could not be saved. Please try again.", keep the title and date in the form and add nothing to the list.
- The web app never shows response bodies, status codes or stack traces to the user. It logs them on the server.

### Timeouts

| Call | Timeout | When the other side is down or slow |
|---|---|---|
| web server → `GET /tasks` | 5 s total (`AbortSignal.timeout(5000)`) | The page renders with the load error text. No retry inside the request; the user reloads. |
| web server → `POST /tasks` | 5 s total | The save error text, and the form keeps its input. **No automatic retry** (a retry after a timeout could create the task twice). |
| API → Postgres, connect / pool checkout | 2 s | `503 {"detail": "database unavailable"}` |
| API → Postgres, statement (`statement_timeout`) | 5 s | `503`. The insert's transaction is rolled back, so no partial task. |
| API `/ready` → `SELECT 1` | 1 s | `503 {"status": "not ready"}`. Kubernetes takes the pod out of the Service; `/health` stays `200`, so the pod is not restarted. |

The API does not cache connection failures. Each request tries the pool again, so service resumes without a restart once the database is back (AC-001.4). The web's 5 s budget covers the API's worst case (2 s connect plus the query), so a database outage reaches the user as a `503`, not as a web timeout.

### Provided by the system

The gitops part of this plan wires these for this repo; rely on them, do not ask for them again:

- resource `postgres`: env `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`

### Notes for this repo

Builds on the API's spec 001 (in memory): keep the routes, models and validation of
src/taskboard3_api/tasks/ and replace the in-memory TaskStore behind get_task_store with a
Postgres store. Connection settings come from DATABASE_URL (PG* are also set); see the
plan's Contract for the table, ordering, 503 body, readiness and timeouts. The API's
acceptance tests need a real Postgres (a throwaway one in tests/CI), not a mock.

## Stories

- As an API client, I want the tasks I created to still be listed after the API was restarted or redeployed, so that I can rely on the list.
- As an API client, I want every running instance of the API to return the same task list, so that it does not matter which instance answers me.
- As an API client, I want `POST /tasks` and `GET /tasks` to behave exactly as before, so that nothing built on spec 001 breaks.
- As an API client (the web app), I want a clear `503` when the database is down and normal answers again once it is back, so that I can tell the user to try again instead of seeing a crash or a lost task.
- As the platform running the API, I want the readiness endpoint to report not ready while the database is down, and the health endpoint to stay healthy, so that traffic is routed away from the instance without restarting it.

## Acceptance criteria

Durable and shared storage:

- **AC-002.1** Given tasks A, B and C were created through `POST /tasks`, when the API is stopped and started again (or a new API instance is started) against the same database, then `GET /tasks` returns `200` with A, B and C in creation order, each with the same `id`, `title` and `due_date` as its create response. (system AC-001.1)
- **AC-002.2** Given two API instances use the same database, when a task is created through the first instance, then `GET /tasks` answered by the second instance includes that task with the same `id`, `title` and `due_date`. (system AC-001.2)
- **AC-002.3** Given two API instances use the same database, when task A is created through the first instance and then task B through the second, then `GET /tasks` answered by either instance lists A before B, and the two ids differ. (system AC-001.2)

Unchanged task contract:

- **AC-002.4** Given the database is reachable, when the acceptance criteria AC-001.1 to AC-001.13 of the API's spec 001 are checked, then each still holds unchanged (same status codes, response bodies, `422` errors naming `title` or `due_date`, trimming, 200-character limit, past dates accepted, creation order, API documentation); for AC-001.4 "no task has been created" means the database holds no task. (system AC-001.3)
- **AC-002.5** Given the database is reachable, when a client creates a task whose trimmed title is exactly 200 non-ASCII characters (for example 200 times `ä`) and a `due_date` of `"2026-12-31"`, then the response is `201`, and the create response and `GET /tasks` both return that title and `"due_date": "2026-12-31"` unchanged. (system AC-001.3)
- **AC-002.6** Given a database with no tasks table yet, when the API connects to it for the first time, then `GET /tasks` returns `200` with `[]` and a following `POST /tasks` returns `201`, without any manual setup step. (system AC-001.3)
- **AC-002.7** Given the database is reachable, when a client sends `GET /tasks` through the service's public URL, then the response is `200` with a JSON array. (system AC-001.3) (smoke)

Database unavailable:

- **AC-002.8** Given the database cannot be reached, when a client sends `GET /tasks`, then the response is `503` with the JSON body `{"detail": "database unavailable"}` within 5 seconds. (system AC-001.4)
- **AC-002.9** Given the database cannot be reached, when a client sends a valid `POST /tasks`, then the response is `503` with the JSON body `{"detail": "database unavailable"}` within 5 seconds, and once the database is reachable again `GET /tasks` does not contain that task. (system AC-001.4)
- **AC-002.10** Given the database is reachable but a task statement takes longer than 5 seconds, when a client sends `POST /tasks` or `GET /tasks`, then the response is `503` with `{"detail": "database unavailable"}`, and no task from that create request appears in a later `GET /tasks`. (system AC-001.4)
- **AC-002.11** Given the database cannot be reached, when a client sends a `POST /tasks` with invalid input (for example an empty `title`), then the response is `422` exactly as in spec 001, not `503`. (system AC-001.3, system AC-001.4)
- **AC-002.12** Given tasks were created, then the database became unreachable and requests were answered with `503`, when the database is reachable again, then without restarting the API a `GET /tasks` returns `200` with all tasks created before the outage in creation order, and a valid `POST /tasks` returns `201`. (system AC-001.4)
- **AC-002.13** Given the database cannot be reached (or no database connection is configured) when the API starts, when the process has started, then it keeps running instead of refusing to start, `GET /health` returns `200 {"status": "ok"}`, `GET /ready` returns `503 {"status": "not ready"}` and `/tasks` requests return `503 {"detail": "database unavailable"}`; once the database is reachable, `POST /tasks` and `GET /tasks` work without restarting the API. (system AC-001.4, system AC-001.5)

Probes:

- **AC-002.14** Given the database is reachable, when `GET /ready` is called, then the response is `200` with `{"status": "ready"}`. (system AC-001.5) (smoke)
- **AC-002.15** Given the database cannot be reached or does not answer within 1 second, when `GET /ready` is called, then the response is `503` with `{"status": "not ready"}`, returned within 2 seconds; when the database is reachable again, the next `GET /ready` returns `200` with `{"status": "ready"}`. (system AC-001.5)
- **AC-002.16** Given the database cannot be reached, when `GET /health` is called, then the response is `200` with `{"status": "ok"}`. (system AC-001.5)

## Non-goals

- Moving tasks held in memory by the currently running API into the database; they are lost once, on the switch.
- Any change to the task contract: new fields, new endpoints, other status codes for invalid input, pagination, editing or deleting tasks.
- Retrying failed database calls inside a request, or queueing creates while the database is down; the client gets `503` and decides.
- Schema versioning or migrations beyond creating the tasks table when it is missing.
- Database backups and restore, and running in staging or prod (system spec 001 non-goals).
- An upper limit on the number of tasks.
- Provisioning the database or its connection settings; the system's gitops repo provides them.

## Open questions

- ~~Confirm: invalid input while the database is down is answered with `422`, not `503` (validation runs before the database is touched).~~ Answered: yes, `422`; see AC-002.11.
- ~~Confirm: when no database connection is configured at all, the API still starts and behaves as with an unreachable database (`/health` 200, `/ready` 503, `/tasks` 503) instead of refusing to start.~~ Answered: yes, it starts and reports not ready; see AC-002.13.
- ~~Confirm: `/ready` answers `503` within 2 seconds when the database does not respond (1 second check plus overhead), and `/tasks` answers `503` within 5 seconds (the web app's budget).~~ Answered: yes, 2 s and 5 s; see AC-002.8, AC-002.9, AC-002.15.
- ~~Spec 001 (done) still says "no task has been created since the service started" (AC-001.4) and lists durable storage as a non-goal. Should spec 001 be amended, or does this spec supersede those lines?~~ Answered: spec 001 stays unchanged; this spec replaces its in-memory lines, and AC-002.4 says how AC-001.4 is read against a database.

## Decisions taken during the ship

- Is invalid input while the database is down answered with `422` or `503`? `422`: validation runs first (AC-002.11).
- Does the API start when no database connection is configured? Yes: it starts and behaves as if the database were unreachable, `/health` `200`, `/ready` `503`, `/tasks` `503` (AC-002.13).
- How fast are the `503` answers while the database does not respond? `/ready` within 2 s, `/tasks` within 5 s (AC-002.8, AC-002.9, AC-002.15).
- Amend spec 001 or supersede its in-memory lines? Leave spec 001 unchanged; this spec replaces its in-memory lines, and AC-002.4 says how AC-001.4 is read against a database (AC-002.4).

## Changelog

- 2026-11-05 created
- 2026-11-05 amended: the four open questions answered with the suggested answers and struck through; AC-002.13 now also states `/ready` `503` and that the API does not refuse to start; added "Decisions taken during the ship".
- 2026-11-05 approved
