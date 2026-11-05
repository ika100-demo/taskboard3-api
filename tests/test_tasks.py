"""Acceptance tests for spec 001: create and list tasks in memory."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from taskboard3_api.main import app
from taskboard3_api.tasks import TaskStore, get_task_store


@pytest.fixture()
def api() -> Iterator[TestClient]:
    store = TaskStore()
    app.dependency_overrides[get_task_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_task_store, None)


def _locs(response) -> list[list]:
    return [entry["loc"] for entry in response.json()["detail"]]


def _names_field(response, field: str) -> bool:
    return any(field in loc for loc in _locs(response))


def test_create_minimal_task(api: TestClient) -> None:  # AC-001.1
    response = api.post("/tasks", json={"title": "Buy milk"})
    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], str) and body["id"]
    assert body["title"] == "Buy milk"
    assert body["due_date"] is None


def test_create_with_due_date(api: TestClient) -> None:  # AC-001.2
    response = api.post("/tasks", json={"title": "File taxes", "due_date": "2026-12-31"})
    assert response.status_code == 201
    assert response.json()["due_date"] == "2026-12-31"


def test_ids_differ(api: TestClient) -> None:  # AC-001.3
    a = api.post("/tasks", json={"title": "A"}).json()
    b = api.post("/tasks", json={"title": "B"}).json()
    assert a["id"] != b["id"]


def test_list_empty(api: TestClient) -> None:  # AC-001.4
    response = api.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_list_in_creation_order(api: TestClient) -> None:  # AC-001.5
    created = [
        api.post("/tasks", json={"title": "A"}).json(),
        api.post("/tasks", json={"title": "B", "due_date": "2026-01-02"}).json(),
        api.post("/tasks", json={"title": "C"}).json(),
    ]
    response = api.get("/tasks")
    assert response.status_code == 200
    assert response.json() == created


@pytest.mark.parametrize("payload", [{}, {"title": ""}, {"title": "   "}])
def test_title_missing_empty_or_blank(api: TestClient, payload: dict) -> None:  # AC-001.6
    response = api.post("/tasks", json=payload)
    assert response.status_code == 422
    assert _names_field(response, "title")
    assert api.get("/tasks").json() == []


def test_title_length_limit(api: TestClient) -> None:  # AC-001.7
    too_long = api.post("/tasks", json={"title": "x" * 201})
    assert too_long.status_code == 422
    assert _names_field(too_long, "title")
    assert api.get("/tasks").json() == []
    ok = api.post("/tasks", json={"title": "x" * 200})
    assert ok.status_code == 201
    assert len(api.get("/tasks").json()) == 1


@pytest.mark.parametrize("value", ["2026-02-30", "31.12.2026", "tomorrow"])
def test_invalid_due_date(api: TestClient, value: str) -> None:  # AC-001.8
    response = api.post("/tasks", json={"title": "T", "due_date": value})
    assert response.status_code == 422
    assert _names_field(response, "due_date")
    assert api.get("/tasks").json() == []


@pytest.mark.parametrize(
    "payload",
    [
        ["Buy milk"],
        "Buy milk",
        {"title": 5},
        {"title": "T", "due_date": 20261231},
    ],
)
def test_wrong_types(api: TestClient, payload: object) -> None:  # AC-001.9
    response = api.post("/tasks", json=payload)
    assert response.status_code == 422
    assert api.get("/tasks").json() == []


def test_due_date_null(api: TestClient) -> None:  # AC-001.10
    response = api.post("/tasks", json={"title": "T", "due_date": None})
    assert response.status_code == 201
    assert response.json()["due_date"] is None


def test_title_is_trimmed(api: TestClient) -> None:  # AC-001.11
    response = api.post("/tasks", json={"title": "  Buy milk  "})
    assert response.status_code == 201
    assert response.json()["title"] == "Buy milk"
    assert api.get("/tasks").json()[0]["title"] == "Buy milk"


def test_openapi_lists_routes(api: TestClient) -> None:  # AC-001.12
    doc = api.get("/openapi.json").json()
    tasks = doc["paths"]["/tasks"]
    assert "post" in tasks and "get" in tasks
    assert "TaskCreate" in str(tasks["post"]["requestBody"])
    assert "201" in tasks["post"]["responses"]
    assert "Task" in str(tasks["post"]["responses"]["201"])
    assert "Task" in str(tasks["get"]["responses"]["200"])


def test_past_due_date_accepted(api: TestClient) -> None:  # AC-001.13
    response = api.post("/tasks", json={"title": "Old", "due_date": "2020-01-15"})
    assert response.status_code == 201
    assert response.json()["due_date"] == "2020-01-15"
