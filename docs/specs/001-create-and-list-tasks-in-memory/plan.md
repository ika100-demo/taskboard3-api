---
spec_id: 001-create-and-list-tasks-in-memory
shape: service-python
spec_hash: 7efebe7f1fc4
summary: In-memory task resource with POST /tasks (validated create) and GET /tasks (list in creation order)
tasks:
  - id: t1
    title: Add task models with validation and the in-memory TaskStore
    files: [src/taskboard3_api/tasks/models.py, src/taskboard3_api/tasks/store.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.5, AC-001.6, AC-001.7, AC-001.8, AC-001.9, AC-001.10, AC-001.11, AC-001.13]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: Expose POST /tasks and GET /tasks via a router wired into the app
    files: [src/taskboard3_api/tasks/api.py, src/taskboard3_api/tasks/__init__.py, src/taskboard3_api/main.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7, AC-001.8, AC-001.9, AC-001.10, AC-001.11, AC-001.12, AC-001.13]
    parallel_safe: false
    depends_on: [t1]
---

# Plan — 001 Create and list tasks (in memory)

Design and contract: [design.md](design.md).

## t1 — Add task models with validation and the in-memory TaskStore

**Files:** src/taskboard3_api/tasks/models.py, src/taskboard3_api/tasks/store.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.5, AC-001.6, AC-001.7, AC-001.8, AC-001.9, AC-001.10, AC-001.11, AC-001.13
**Goal:** the domain layer of the task resource: a request model that enforces every input rule of the spec, a response model, and a thread-safe in-memory store that assigns ids and keeps creation order.

**Implementation notes:**
- `TaskCreate(BaseModel)`: `title: str` and `due_date: str | None = None`, both with `Field(strict=True)` so numbers, booleans, arrays and objects are rejected rather than coerced (AC-001.9). Extra fields ignored (Pydantic default).
- `title` after-validator: `strip()`, then reject when empty (AC-001.6) or `len > 200` (AC-001.7); return the trimmed value (AC-001.11). Raise `ValueError` so the error lands at `loc ["body", "title"]`.
- `due_date` after-validator (skipped for `None`, AC-001.10): require `re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)` and `datetime.date.fromisoformat(v)` succeeding (rejects `2026-02-30`, `31.12.2026`, `tomorrow`, AC-001.8); return the input string unchanged, no "not in the past" check (AC-001.2, AC-001.13).
- `Task(BaseModel)`: `id: str`, `title: str`, `due_date: str | None` (always serialized, `null` when absent, AC-001.1).
- `TaskStore`: private `list[Task]` plus `threading.Lock`; `add(data: TaskCreate) -> Task` builds `Task(id=str(uuid.uuid4()), ...)` and appends (AC-001.3); `list() -> list[Task]` returns a copy in insertion order (AC-001.5).
- `get_task_store() -> TaskStore`: returns one module-level instance.
- Docstrings and full type hints; `mypy --strict` clean.

**Done when:** `devbox run quality` passes; the module-level behaviour matches design.md's Interfaces (the acceptance tests exercise it through HTTP once t2 lands).

## t2 — Expose POST /tasks and GET /tasks via a router wired into the app

**Files:** src/taskboard3_api/tasks/api.py, src/taskboard3_api/tasks/__init__.py, src/taskboard3_api/main.py
**Covers:** AC-001.1 to AC-001.13 (all)
**Goal:** the HTTP surface defined in design.md's Contract, documented in the generated OpenAPI.

**Implementation notes:**
- `api.py`: `router = APIRouter(tags=["tasks"])`.
- `POST /tasks`: `status_code=201`, `response_model=Task`, body `TaskCreate`, `store: TaskStore = Depends(get_task_store)`; returns `store.add(body)`. Validation failures never reach the handler, so nothing is stored on `422` (AC-001.6 to AC-001.9).
- `GET /tasks`: `response_model=list[Task]`, returns `store.list()` (AC-001.4, AC-001.5).
- Sync `def` handlers (the store is lock-guarded); no custom exception handler: FastAPI's default 422 body is the contract.
- Give both routes a `summary` so they read well in `/docs`; request and response schemas come from the models (AC-001.12).
- `__init__.py`: re-export `router`, `TaskStore`, `get_task_store`, `Task`, `TaskCreate` (tests import `get_task_store` and `TaskStore` from `taskboard3_api.tasks`).
- `main.py`: `from .tasks import router as tasks_router` and `app.include_router(tasks_router)` after the middleware; leave health, ready, ping and metrics unchanged.

**Done when:** all acceptance tests for AC-001.1 to AC-001.13 pass with `devbox run test`, the existing health/metrics/tracing tests still pass, and `devbox run quality` is green.
