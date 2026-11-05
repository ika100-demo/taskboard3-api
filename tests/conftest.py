"""Shared pytest fixtures, including a throwaway Postgres cluster (spec 002)."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess  # noqa: S404
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def free_port() -> int:
    """A TCP port nothing listens on (bind, read, close)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_psql(url: str, sql: str) -> str:
    """Run one SQL string through psql against url; return stdout."""
    result = subprocess.run(  # noqa: S603
        ["psql", url, "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", sql],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout.strip()


class Cluster:
    """A Postgres cluster in a temp dir, TCP only, that can be stopped and started again."""

    def __init__(self, root: Path, port: int | None = None) -> None:
        missing = [name for name in ("initdb", "pg_ctl") if shutil.which(name) is None]
        if missing:
            pytest.fail("initdb/pg_ctl not on PATH: run the tests through `devbox run test`")
        self.port = port or free_port()
        self.data = root / "data"
        self.log = root / "log"
        root.mkdir(parents=True, exist_ok=True)
        subprocess.run(  # noqa: S603
            ["initdb", "-D", str(self.data), "-U", "postgres", "-A", "trust", "-E", "UTF8"]  # noqa: S607
            + ["--no-locale"],
            capture_output=True,
            check=True,
            timeout=120,
        )

    @property
    def url(self) -> str:
        return f"postgresql://postgres@127.0.0.1:{self.port}/postgres"

    def start(self) -> None:
        opts = f"-p {self.port} -c listen_addresses=127.0.0.1 -c unix_socket_directories=''"
        subprocess.run(  # noqa: S603
            ["pg_ctl", "-D", str(self.data), "-l", str(self.log), "-w", "-o", opts, "start"],  # noqa: S607
            capture_output=True,
            check=True,
            timeout=120,
        )

    def stop(self) -> None:
        subprocess.run(  # noqa: S603
            ["pg_ctl", "-D", str(self.data), "-m", "immediate", "-w", "stop"],  # noqa: S607
            capture_output=True,
            check=False,
            timeout=120,
        )


@pytest.fixture(scope="session")
def postgres_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """URL of a throwaway Postgres cluster; also sets DATABASE_URL for the session."""
    cluster = Cluster(tmp_path_factory.mktemp("pg-session"))
    cluster.start()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = cluster.url
    try:
        yield cluster.url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        cluster.stop()


@pytest.fixture()
def psql(postgres_url: str) -> Callable[[str, str], str]:
    """The run_psql helper: psql(url, sql)."""
    return run_psql


@pytest.fixture()
def clean_tasks(postgres_url: str) -> str:
    """Truncate the tasks table (when it exists) and return the session URL."""
    run_psql(
        postgres_url,
        "DO $$ BEGIN IF to_regclass('public.tasks') IS NOT NULL THEN "
        "TRUNCATE tasks RESTART IDENTITY; END IF; END $$;",
    )
    return postgres_url


@pytest.fixture()
def cluster_factory(tmp_path: Path) -> Iterator[Callable[..., Cluster]]:
    """Create function-scoped clusters (not started); all are stopped at teardown."""
    made: list[Cluster] = []

    def make(port: int | None = None) -> Cluster:
        cluster = Cluster(tmp_path / f"pg-{len(made)}", port)
        made.append(cluster)
        return cluster

    yield make
    for cluster in made:
        cluster.stop()


@pytest.fixture()
def dead_url() -> str:
    """A URL whose port refuses connections."""
    return f"postgresql://postgres@127.0.0.1:{free_port()}/postgres"


@pytest.fixture()
def client(postgres_url: str) -> TestClient:
    """A TestClient for the FastAPI application (module-level app, DATABASE_URL set)."""
    from taskboard3_api.main import app

    return TestClient(app)
