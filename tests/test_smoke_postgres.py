"""Smoke tests (spec 002): reach the service only through its URL."""

from __future__ import annotations

import json
import urllib.request

import pytest


def _get(url: str) -> tuple[int, object]:
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
        return int(response.status), json.load(response)


@pytest.mark.smoke
def test_ac_002_7_list_tasks_returns_array(smoke_base_url: str) -> None:  # AC-002.7
    status, body = _get(smoke_base_url + "/tasks")
    assert status == 200
    assert isinstance(body, list)


@pytest.mark.smoke
def test_ac_002_14_ready_reports_ready(smoke_base_url: str) -> None:  # AC-002.14
    status, body = _get(smoke_base_url + "/ready")
    assert status == 200
    assert body == {"status": "ready"}
