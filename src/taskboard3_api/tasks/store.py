"""Postgres-backed task store."""

from __future__ import annotations

import datetime
import uuid

from fastapi import Request

from taskboard3_api.db import Database
from taskboard3_api.tasks.models import Task, TaskCreate


class TaskStore:
    """Persists tasks in the ``tasks`` table, listed in creation order."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def add(self, data: TaskCreate) -> Task:
        """Assign an id to the new task, store it and return it as stored."""
        due = datetime.date.fromisoformat(data.due_date) if data.due_date else None
        with self._database.transaction() as conn:
            row = conn.execute(
                "INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s) "
                "RETURNING id, title, due_date",
                (str(uuid.uuid4()), data.title, due),
            ).fetchone()
        assert row is not None  # noqa: S101 - INSERT ... RETURNING always yields a row
        return Task(
            id=row[0],
            title=row[1],
            due_date=row[2].isoformat() if row[2] is not None else None,
        )

    def list(self) -> list[Task]:
        """Return all tasks in creation order."""
        with self._database.transaction() as conn:
            rows = conn.execute("SELECT id, title, due_date FROM tasks ORDER BY seq").fetchall()
        return [
            Task(id=r[0], title=r[1], due_date=r[2].isoformat() if r[2] is not None else None)
            for r in rows
        ]


def get_task_store(request: Request) -> TaskStore:
    """Return a store bound to the application's database."""
    return TaskStore(request.app.state.database)
