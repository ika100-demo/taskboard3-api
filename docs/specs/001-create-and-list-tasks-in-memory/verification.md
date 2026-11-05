# Verification — 001 Create and list tasks (in memory)

**Result:** pass
**Commit:** c06fe91 · **Base:** dc876ef · **Trace:** 13/13 criteria named by tests (AC-001.1 and AC-001.5 also by smoke tests)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-001.1 | met | `tests/test_tasks.py::test_create_minimal_task`, `tests/test_smoke_tasks.py::test_ac_001_1_created_task_is_listed` (smoke, writes) | `src/taskboard3_api/tasks/api.py:15`, `src/taskboard3_api/tasks/store.py:18` | asserts 201, non-empty string id, the exact title, `due_date` null |
| AC-001.2 | met | `tests/test_tasks.py::test_create_with_due_date` | `src/taskboard3_api/tasks/models.py:29-41` | the date string comes back unchanged; the regex and `fromisoformat` reject a time part |
| AC-001.3 | met | `tests/test_tasks.py::test_ids_differ` | `src/taskboard3_api/tasks/store.py:18` (`uuid4`) | |
| AC-001.4 | met | `tests/test_tasks.py::test_list_empty` | `src/taskboard3_api/tasks/api.py:21-24`, `src/taskboard3_api/tasks/store.py:13` | each test gets its own store through the dependency override |
| AC-001.5 | met | `tests/test_tasks.py::test_list_in_creation_order`, `tests/test_smoke_tasks.py::test_ac_001_5_list_tasks_returns_array`, `tests/test_smoke_tasks.py::test_ac_001_1_created_task_is_listed` | `src/taskboard3_api/tasks/store.py:20,23-26` | full equality of the list with the three create responses, in order A, B, C |
| AC-001.6 | met | `tests/test_tasks.py::test_title_missing_empty_or_blank` (`{}`, `""`, `"   "`) | `src/taskboard3_api/tasks/models.py:15,22-24` | 422, `title` in `loc`, list still empty |
| AC-001.7 | met | `tests/test_tasks.py::test_title_length_limit` | `src/taskboard3_api/tasks/models.py:25-26` | 201 characters gives 422 with `title` and no task stored; exactly 200 gives 201 |
| AC-001.8 | met | `tests/test_tasks.py::test_invalid_due_date` (`2026-02-30`, `31.12.2026`, `tomorrow`) | `src/taskboard3_api/tasks/models.py:35-40` | 422, `due_date` in `loc`, nothing stored |
| AC-001.9 | met | `tests/test_tasks.py::test_wrong_types` (array, string body, numeric title, numeric due_date) | `src/taskboard3_api/tasks/models.py:15-16` (`strict=True`) | 422 and nothing stored, for both "not an object" and "wrong field type" |
| AC-001.10 | met | `tests/test_tasks.py::test_due_date_null` | `src/taskboard3_api/tasks/models.py:16,33-34` | same result as omitting the field (AC-001.1) |
| AC-001.11 | met | `tests/test_tasks.py::test_title_is_trimmed` | `src/taskboard3_api/tasks/models.py:22` | checks both the returned and the stored (listed) title |
| AC-001.12 | met | `tests/test_tasks.py::test_openapi_lists_routes` | `src/taskboard3_api/tasks/api.py:15,21`, `src/taskboard3_api/main.py:24` | checks the `TaskCreate` request schema and the `Task` schema in the POST 201 and GET 200 responses of `/openapi.json` |
| AC-001.13 | met | `tests/test_tasks.py::test_past_due_date_accepted` | `src/taskboard3_api/tasks/models.py:29-41` (no check that the date is in the future) | |

## Non-goals

No persistence, no single-task read, update or delete, no filtering or pagination, no auth, no time zones, no extra fields (`created_at` included) and no task-count limit. `Task` has only `id`, `title`, `due_date` (`src/taskboard3_api/tasks/models.py:44-49`). ✔

Template-owned layout: `main.py` gets only the router import and `include_router` (`src/taskboard3_api/main.py:15,24`); health, ready, ping, metrics, logging and tracing are unchanged. ✔

## Deviations from the plan

- `docs/specs/001-create-and-list-tasks-in-memory/{spec,design,plan}.md` and `tests/test_tasks.py` / `tests/test_smoke_tasks.py` are in no task's `files`. Acceptable: these are the spec files and the acceptance tests from red commit 52096b7, and the tests have not changed since (`git diff 52096b7..HEAD` touches only plan.md and `src/`).
- Both tasks t1 and t2 are `done: true`.
- `api.py` uses `Annotated[TaskStore, Depends(get_task_store)]` where the plan says `= Depends(...)`. The behaviour is the same, so this is acceptable.

## Contract

Matches `design.md`: `POST /tasks` returns 201 with `Task` and FastAPI's default 422 with `loc ["body", <field>]`, and no custom handler was added. `GET /tasks` returns 200 with `Task[]` in creation order. The interfaces `TaskCreate`, `Task`, `TaskStore.add/list` and `get_task_store` match, and `__init__.py` re-exports them as planned. ✔

Minor note, not a failure: `\d` in `_DATE_RE` (`models.py:8`) also matches non-ASCII digits. `date.fromisoformat` is the second check behind it. No criterion covers this, so it needs no action for this spec.
