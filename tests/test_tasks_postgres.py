"""Acceptance tests for spec 002: tasks live in Postgres."""

from __future__ import annotations

import socket
import subprocess  # noqa: S404
import time
from collections.abc import Callable, Iterator

import pytest
from conftest import Cluster, run_psql
from fastapi.testclient import TestClient

UNAVAILABLE = {"detail": "database unavailable"}
NOT_READY = {"status": "not ready"}


def _app(url: str | None) -> TestClient:
    from taskboard3_api.db import Database

    from taskboard3_api.main import create_app

    return TestClient(create_app(Database.from_url(url)))


def _create(c: TestClient, title: str, due: str | None = None) -> dict:
    response = c.post("/tasks", json={"title": title, "due_date": due})
    assert response.status_code == 201
    return response.json()


def test_tasks_survive_restart(clean_tasks: str) -> None:  # AC-002.1
    first = _app(clean_tasks)
    created = [_create(first, "A"), _create(first, "B", "2026-05-01"), _create(first, "C")]
    del first
    restarted = _app(clean_tasks)
    response = restarted.get("/tasks")
    assert response.status_code == 200
    assert response.json() == created


def test_second_instance_sees_task(clean_tasks: str) -> None:  # AC-002.2
    one, two = _app(clean_tasks), _app(clean_tasks)
    created = _create(one, "shared", "2026-03-04")
    listed = two.get("/tasks").json()
    assert created in listed


def test_order_across_instances(clean_tasks: str) -> None:  # AC-002.3
    one, two = _app(clean_tasks), _app(clean_tasks)
    a = _create(one, "A")
    b = _create(two, "B")
    assert a["id"] != b["id"]
    for instance in (one, two):
        assert instance.get("/tasks").json() == [a, b]


def test_invalid_input_creates_no_row(clean_tasks: str) -> None:  # AC-002.4
    api = _app(clean_tasks)
    assert api.post("/tasks", json={"title": ""}).status_code == 422
    assert run_psql(clean_tasks, "SELECT count(*) FROM tasks") == "0"


def test_200_non_ascii_characters(clean_tasks: str) -> None:  # AC-002.5
    api = _app(clean_tasks)
    title = "ä" * 200
    response = api.post("/tasks", json={"title": f"  {title} ", "due_date": "2026-12-31"})
    assert response.status_code == 201
    assert response.json()["title"] == title
    assert response.json()["due_date"] == "2026-12-31"
    listed = api.get("/tasks").json()
    assert listed == [response.json()]


def test_table_created_on_first_connect(clean_tasks: str) -> None:  # AC-002.6
    run_psql(clean_tasks, "DROP TABLE IF EXISTS tasks")
    api = _app(clean_tasks)
    assert api.get("/tasks").status_code == 200
    assert api.get("/tasks").json() == []
    run_psql(clean_tasks, "DROP TABLE IF EXISTS tasks")
    fresh = _app(clean_tasks)
    assert fresh.get("/tasks").json() == []
    assert fresh.post("/tasks", json={"title": "first"}).status_code == 201


def test_get_tasks_503_when_db_down(dead_url: str) -> None:  # AC-002.8
    api = _app(dead_url)
    start = time.monotonic()
    response = api.get("/tasks")
    assert time.monotonic() - start < 5
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE


def test_post_503_when_db_down_stores_nothing(
    cluster_factory: Callable[..., Cluster],
) -> None:  # AC-002.9
    cluster = cluster_factory()
    cluster.start()
    api = _app(cluster.url)
    assert api.get("/tasks").status_code == 200
    cluster.stop()
    start = time.monotonic()
    response = api.post("/tasks", json={"title": "lost"})
    assert time.monotonic() - start < 5
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE
    cluster.start()
    listed = api.get("/tasks")
    assert listed.status_code == 200
    assert all(task["title"] != "lost" for task in listed.json())


@pytest.fixture()
def table_lock(clean_tasks: str) -> Iterator[Callable[[], None]]:
    """Hold ACCESS EXCLUSIVE on tasks in another session until released."""
    state: dict[str, subprocess.Popen] = {}

    def acquire() -> None:
        proc = subprocess.Popen(  # noqa: S603
            [  # noqa: S607
                "psql",
                clean_tasks,
                "-X",
                "-c",
                "BEGIN; LOCK TABLE tasks IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(60);",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        state["proc"] = proc
        query = "SELECT count(*) FROM pg_locks WHERE mode = 'AccessExclusiveLock' AND granted"
        query += " AND relation = 'tasks'::regclass"
        for _ in range(50):
            if run_psql(clean_tasks, query) != "0":
                return
            time.sleep(0.2)
        pytest.fail("lock was not acquired")

    yield acquire
    if "proc" in state:
        state["proc"].kill()
        state["proc"].wait()


def test_slow_statement_gives_503(
    clean_tasks: str, table_lock: Callable[[], None]
) -> None:  # AC-002.10
    api = _app(clean_tasks)
    assert api.get("/tasks").status_code == 200  # schema bootstrapped
    table_lock()
    start = time.monotonic()
    response = api.post("/tasks", json={"title": "slow-one"})
    assert 4 < time.monotonic() - start < 9
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE
    response = api.get("/tasks")
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE


def test_slow_statement_task_not_stored(
    clean_tasks: str, table_lock: Callable[[], None]
) -> None:  # AC-002.10
    api = _app(clean_tasks)
    assert api.get("/tasks").status_code == 200
    table_lock()
    assert api.post("/tasks", json={"title": "slow-two"}).status_code == 503
    # release the lock by ending the holding session
    run_psql(
        clean_tasks,
        "SELECT pg_terminate_backend(pid) FROM pg_locks WHERE mode = 'AccessExclusiveLock' "
        "AND relation = 'tasks'::regclass AND pid <> pg_backend_pid()",
    )
    for _ in range(20):
        response = api.get("/tasks")
        if response.status_code == 200:
            break
        time.sleep(0.5)
    assert response.status_code == 200
    assert all(task["title"] != "slow-two" for task in response.json())


def test_invalid_input_is_422_not_503(dead_url: str) -> None:  # AC-002.11
    api = _app(dead_url)
    response = api.post("/tasks", json={"title": ""})
    assert response.status_code == 422
    assert any("title" in entry["loc"] for entry in response.json()["detail"])


def test_recovery_without_restart(cluster_factory: Callable[..., Cluster]) -> None:  # AC-002.12
    cluster = cluster_factory()
    cluster.start()
    api = _app(cluster.url)
    created = [_create(api, "one"), _create(api, "two")]
    cluster.stop()
    assert api.get("/tasks").status_code == 503
    assert api.post("/tasks", json={"title": "during"}).status_code == 503
    cluster.start()
    response = api.get("/tasks")
    assert response.status_code == 200
    assert response.json() == created
    assert api.post("/tasks", json={"title": "after"}).status_code == 201


def test_starts_without_database_configured(
    postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:  # AC-002.13
    from taskboard3_api.main import create_app

    monkeypatch.delenv("DATABASE_URL", raising=False)
    api = TestClient(create_app())
    assert api.get("/health").json() == {"status": "ok"}
    ready = api.get("/ready")
    assert ready.status_code == 503
    assert ready.json() == NOT_READY
    for response in (api.get("/tasks"), api.post("/tasks", json={"title": "x"})):
        assert response.status_code == 503
        assert response.json() == UNAVAILABLE
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    assert api.get("/tasks").status_code == 200
    assert api.post("/tasks", json={"title": "now"}).status_code == 201


def test_starts_with_unreachable_database(
    cluster_factory: Callable[..., Cluster],
) -> None:  # AC-002.13
    cluster = cluster_factory()  # initialised, not started: port refuses
    api = _app(cluster.url)
    assert api.get("/health").json() == {"status": "ok"}
    assert api.get("/ready").status_code == 503
    assert api.get("/tasks").json() == UNAVAILABLE
    cluster.start()
    assert api.get("/ready").json() == {"status": "ready"}
    assert api.post("/tasks", json={"title": "up"}).status_code == 201
    assert len(api.get("/tasks").json()) == 1


def test_ready_when_database_reachable(clean_tasks: str) -> None:  # AC-002.14
    response = _app(clean_tasks).get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_503_when_unreachable_then_recovers(
    clean_tasks: str,
) -> None:  # AC-002.15
    from taskboard3_api.db import Database

    from taskboard3_api.main import create_app

    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen(16)  # accepts TCP connections in the backlog, never answers
        holder = {"url": f"postgresql://postgres@127.0.0.1:{silent.getsockname()[1]}/postgres"}
        api = TestClient(create_app(Database(lambda: holder["url"])))
        start = time.monotonic()
        response = api.get("/ready")
        assert time.monotonic() - start < 2
        assert response.status_code == 503
        assert response.json() == NOT_READY
    holder["url"] = clean_tasks
    response = api.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_503_on_refused_port(dead_url: str) -> None:  # AC-002.15
    start = time.monotonic()
    response = _app(dead_url).get("/ready")
    assert time.monotonic() - start < 2
    assert response.status_code == 503
    assert response.json() == NOT_READY


def test_health_ok_when_db_down(dead_url: str) -> None:  # AC-002.16
    response = _app(dead_url).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
