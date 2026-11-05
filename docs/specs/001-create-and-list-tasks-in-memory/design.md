# Design — 001 Create and list tasks (in memory)

## Decisions

- **A `tasks` subpackage with an `APIRouter`**, included by `main.py`. `main.py` keeps only app wiring; the task resource lives in `src/taskboard3_api/tasks/` (models, store, router), the pattern later resources follow.
- **In-memory store behind a FastAPI dependency.** `TaskStore` holds tasks in a list (creation order, AC-001.5) guarded by a `threading.Lock` (sync endpoints run in the threadpool). One process-wide instance is returned by the dependency `get_task_store()`; tests replace it via `app.dependency_overrides[get_task_store]` with a fresh `TaskStore()`. A durable store later swaps in behind the same methods. Per-instance state is accepted by the spec (Non-goals).
- **Validation in the Pydantic request model, strict types.** Pydantic's lax mode would coerce a number into a date (unix timestamp) and accept `"2026-12-31T00:00:00"` as a date; the spec rejects both (AC-001.8, AC-001.9). So `title` and `due_date` are declared as strict strings and parsed by validators. FastAPI's own 422 response is the error format: no custom handler.
- **`due_date` stays a string on the wire and in the store**, validated as `^\d{4}-\d{2}-\d{2}$` plus `datetime.date.fromisoformat` (which rejects `2026-02-30`). Returned exactly as sent (AC-001.2, AC-001.13); past dates are allowed.
- **Title is trimmed first, then length-checked.** The 1..200 character bound (Python `len`, code points) applies to the trimmed title (AC-001.6, AC-001.7, AC-001.11).
- **ids are `str(uuid.uuid4())`**: unique without a counter, opaque to clients (AC-001.3).
- No ADR: every choice here is local to this feature.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard3_api/tasks/__init__.py` | package; re-exports `router`, `TaskStore`, `get_task_store` | new |
| `src/taskboard3_api/tasks/models.py` | `TaskCreate` (request, validation), `Task` (response) | new |
| `src/taskboard3_api/tasks/store.py` | `TaskStore` (thread-safe, in memory), `get_task_store()` | new |
| `src/taskboard3_api/tasks/api.py` | `router` with `POST /tasks`, `GET /tasks` | new |
| `src/taskboard3_api/main.py` | `app.include_router(tasks.router)` | changed |

### Interfaces

```python
# models.py
class TaskCreate(BaseModel):          # extra fields are ignored
    title: str                        # strict str; stripped; 1..200 chars after strip
    due_date: str | None = None       # strict str or null; YYYY-MM-DD, real calendar date

class Task(BaseModel):
    id: str
    title: str
    due_date: str | None

# store.py
class TaskStore:
    def add(self, data: TaskCreate) -> Task: ...   # assigns id, appends
    def list(self) -> list[Task]: ...              # copy, creation order

def get_task_store() -> TaskStore: ...             # the process-wide instance
```

## Contract

All bodies are `application/json`. Both routes appear in the generated OpenAPI document at `GET /openapi.json` (and the UI at `/docs`), with `TaskCreate` as the request schema and `Task` / `Task[]` as response schemas (AC-001.12).

### `POST /tasks`

Request body (a JSON object):

| Field | Type | Required | Rules |
|---|---|---|---|
| `title` | string | yes | leading/trailing whitespace trimmed; after trimming 1 to 200 characters |
| `due_date` | string or `null` | no (default `null`) | `YYYY-MM-DD`, a real calendar date; past dates allowed |

Unknown fields are ignored.

Responses:

- `201` → `{"id": str (non-empty, UUID4), "title": str (trimmed), "due_date": str | null}` (AC-001.1, AC-001.2, AC-001.10, AC-001.11, AC-001.13).
- `422` → FastAPI's validation error, and no task is stored (AC-001.6 to AC-001.9):

  ```json
  {"detail": [{"type": "<error type>", "loc": ["body", "<field>"], "msg": "<message>", "input": <value>}]}
  ```

  - `title` missing, empty, whitespace-only, longer than 200 characters, or not a string → an entry with `loc == ["body", "title"]`.
  - `due_date` not a string/null, wrong format or impossible date → an entry with `loc == ["body", "due_date"]`.
  - Body not a JSON object (array, string, number, invalid JSON) → `422` with at least one `detail` entry whose `loc` starts with `"body"`; no field is guaranteed.

  Tests check the field name by `"title"` / `"due_date"` appearing in some `detail[*].loc`; `type` and `msg` texts are not part of the contract.

### `GET /tasks`

- `200` → JSON array of `Task` objects in creation order, each identical to its create response; `[]` when none were created since start (AC-001.4, AC-001.5). No pagination, filtering or limit.

## Data

In memory only: a `list[Task]` inside `TaskStore`. Lost on restart; not shared between instances (spec Non-goals).

## Testing notes

- In-process acceptance tests isolate state by overriding the dependency:
  `app.dependency_overrides[get_task_store] = lambda: store` with `store = TaskStore()`, cleared after the test (import from `taskboard3_api.tasks`).
- Smoke tests against a deployed instance cannot assume an empty list (AC-001.4 is in-process only); they create `smoke-<uuid>` titles, are marked `@pytest.mark.writes`, and find their own tasks in `GET /tasks`. A read-only smoke check of `GET /tasks` returning `200` and an array runs in every environment.

## Risks

- Unbounded memory growth: accepted by the spec (no task limit), revisit with persistence.
- Multiple replicas show different lists: accepted by the spec.
