"""Thread-safe in-memory task store."""

import threading
import uuid

from taskboard3_api.tasks.models import Task, TaskCreate


class TaskStore:
    """Keeps tasks in memory in creation order."""

    def __init__(self) -> None:
        self._tasks: list[Task] = []
        self._lock = threading.Lock()

    def add(self, data: TaskCreate) -> Task:
        """Assign an id to the new task, store it and return it."""
        task = Task(id=str(uuid.uuid4()), title=data.title, due_date=data.due_date)
        with self._lock:
            self._tasks.append(task)
        return task

    def list(self) -> "list[Task]":
        """Return a copy of all tasks in creation order."""
        with self._lock:
            return self._tasks.copy()


_store = TaskStore()


def get_task_store() -> TaskStore:
    """Return the process-wide task store."""
    return _store
