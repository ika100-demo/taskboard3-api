"""Pydantic models for the task resource."""

import datetime
import re

from pydantic import BaseModel, Field, field_validator

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_MAX_TITLE_LENGTH = 200


class TaskCreate(BaseModel):
    """Request body for creating a task."""

    title: str = Field(strict=True)
    due_date: str | None = Field(default=None, strict=True)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: str) -> str:
        """Trim the title and enforce 1..200 characters."""
        v = v.strip()
        if not v:
            raise ValueError("title must not be empty")
        if len(v) > _MAX_TITLE_LENGTH:
            raise ValueError(f"title must be at most {_MAX_TITLE_LENGTH} characters")
        return v

    @field_validator("due_date")
    @classmethod
    def _validate_due_date(cls, v: str | None) -> str | None:
        """Require a real calendar date in YYYY-MM-DD form."""
        if v is None:
            return v
        if not _DATE_RE.fullmatch(v):
            raise ValueError("due_date must be a date in YYYY-MM-DD format")
        try:
            datetime.date.fromisoformat(v)
        except ValueError as exc:
            raise ValueError("due_date must be a valid calendar date") from exc
        return v


class Task(BaseModel):
    """A stored task."""

    id: str
    title: str
    due_date: str | None
