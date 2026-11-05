"""Smoke tests (spec 001, AC-001.1 and AC-001.5): reach the service only through its URL."""

from __future__ import annotations

import json
import urllib.request
import uuid

import pytest


def _request(url: str, payload: dict | None = None) -> tuple[int, object]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(  # noqa: S310
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as response:  # noqa: S310
        return int(response.status), json.load(response)


@pytest.mark.smoke
def test_ac_001_5_list_tasks_returns_array(smoke_base_url: str) -> None:  # AC-001.5
    status, body = _request(smoke_base_url + "/tasks")
    assert status == 200
    assert isinstance(body, list)


@pytest.mark.smoke
@pytest.mark.writes
def test_ac_001_1_created_task_is_listed(smoke_base_url: str) -> None:  # AC-001.1, AC-001.5
    title = f"smoke-{uuid.uuid4()}"
    status, created = _request(smoke_base_url + "/tasks", {"title": title})
    assert status == 201
    assert created["title"] == title
    assert created["id"]
    assert created["due_date"] is None
    _, listed = _request(smoke_base_url + "/tasks")
    assert created in listed
