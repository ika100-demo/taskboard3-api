"""Postgres access: connections, schema bootstrap and readiness ping."""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import TupleRow

CONNECT_TIMEOUT_S = 2
STATEMENT_TIMEOUT_MS = 5000
READY_TIMEOUT_S = 1.0
DATABASE_URL_ENV = "DATABASE_URL"

_SCHEMA_LOCK_KEY = 726_002_001

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS tasks (
    seq      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id       text         NOT NULL UNIQUE,
    title    varchar(200) NOT NULL,
    due_date date         NULL
)
"""


class DatabaseUnavailable(Exception):  # noqa: N818 - name fixed by the design contract
    """No URL configured, connect failed/timed out, or a statement failed operationally."""


class Database:
    """Access to the Postgres database behind a (possibly late-bound) URL."""

    def __init__(self, url_source: Callable[[], str | None]) -> None:
        """Create a database handle; ``url_source`` is called on every use."""
        self._url_source = url_source
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    @classmethod
    def from_env(cls) -> Database:
        """Build a handle reading ``DATABASE_URL`` from the environment on each use."""
        return cls(lambda: os.environ.get(DATABASE_URL_ENV))

    @classmethod
    def from_url(cls, url: str | None) -> Database:
        """Build a handle with a fixed URL; None or blank means not configured."""
        return cls(lambda: url)

    def _url(self) -> str:
        url = self._url_source()
        if url is None or not url.strip():
            raise DatabaseUnavailable("database not configured")
        return url

    def _ensure_schema(self, url: str) -> None:
        """Create the schema once per instance, in its own committed transaction."""
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            conn = self._connect(url)
            try:
                with conn:
                    conn.execute("SELECT pg_advisory_xact_lock(%s)", (_SCHEMA_LOCK_KEY,))
                    conn.execute(_CREATE_TABLE)
            finally:
                conn.close()
            self._schema_ready = True

    @staticmethod
    def _connect(url: str) -> psycopg.Connection[TupleRow]:
        return psycopg.connect(
            url,
            connect_timeout=CONNECT_TIMEOUT_S,
            options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
            client_encoding="utf8",
        )

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection[TupleRow]]:
        """Yield a connection in a transaction: commit on success, rollback on error."""
        url = self._url()
        conn: psycopg.Connection[TupleRow] | None = None
        try:
            try:
                self._ensure_schema(url)
                conn = self._connect(url)
            except (
                psycopg.OperationalError,
                psycopg.InterfaceError,
                psycopg.ProgrammingError,
            ) as exc:
                raise DatabaseUnavailable("database unavailable") from exc
            try:
                with conn:
                    yield conn
            except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
                raise DatabaseUnavailable("database unavailable") from exc
        finally:
            if conn is not None:
                conn.close()

    async def ping(self) -> bool:
        """Return True if the database answers ``SELECT 1`` in time; never raises."""
        try:
            return await asyncio.wait_for(self._ping(), READY_TIMEOUT_S)
        except Exception:
            return False

    async def _ping(self) -> bool:
        url = self._url_source()
        if url is None or not url.strip():
            return False
        conn = await psycopg.AsyncConnection.connect(
            url, connect_timeout=CONNECT_TIMEOUT_S, options="-c statement_timeout=1000"
        )
        try:
            await conn.execute("SELECT 1")
        finally:
            await conn.close()
        return True
