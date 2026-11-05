"""HTTP routes for tasks."""

from typing import Annotated

from fastapi import APIRouter, Depends

from taskboard3_api.tasks.models import Task, TaskCreate
from taskboard3_api.tasks.store import TaskStore, get_task_store

router = APIRouter(tags=["tasks"])

StoreDep = Annotated[TaskStore, Depends(get_task_store)]


@router.post("/tasks", status_code=201, response_model=Task, summary="Create a task")
def create_task(body: TaskCreate, store: StoreDep) -> Task:
    """Create a task and return it."""
    return store.add(body)


@router.get("/tasks", response_model=list[Task], summary="List all tasks")
def list_tasks(store: StoreDep) -> list[Task]:
    """Return all tasks in creation order."""
    return store.list()
