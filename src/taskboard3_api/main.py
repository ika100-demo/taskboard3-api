"""FastAPI entry point for taskboard3-api."""

from __future__ import annotations

import os

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from . import __version__
from .db import Database, DatabaseUnavailable
from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .tasks import router as tasks_router
from .tracing import configure_tracing, tracing_enabled

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
if tracing_enabled():
    configure_tracing()

logger = structlog.get_logger()


class HealthResponse(BaseModel):
    status: str


async def database_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    """Answer 503 when the database cannot be used; never log the URL."""
    logger.warning(
        "database_unavailable",
        route=request.url.path,
        error_type=type(exc).__name__,
    )
    return JSONResponse(status_code=503, content={"detail": "database unavailable"})


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Answer 500 with a generic body; the exception is logged."""
    logger.error(
        "unhandled_exception",
        route=request.url.path,
        error_type=type(exc).__name__,
        exc_info=exc,
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


def create_app(database: Database | None = None) -> FastAPI:
    """Build the application; the database defaults to the environment's."""
    app = FastAPI(title="taskboard3-api", version=__version__)
    app.state.database = database or Database.from_env()
    app.add_middleware(MetricsMiddleware)
    app.include_router(tasks_router)
    app.add_exception_handler(DatabaseUnavailable, database_unavailable_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Liveness probe — returns 200 as long as the process is responding."""
        return HealthResponse(status="ok")

    @app.get("/ready", response_model=HealthResponse)
    async def ready(request: Request) -> HealthResponse | JSONResponse:
        """Readiness probe — 200 when the database answers, else 503."""
        if await request.app.state.database.ping():
            return HealthResponse(status="ready")
        return JSONResponse(status_code=503, content={"status": "not ready"})

    @app.get("/ping")
    def ping() -> dict[str, str]:
        """Simple ping endpoint."""
        return {"pong": "taskboard3-api"}

    @app.get("/metrics")
    def metrics() -> Response:
        """Prometheus scrape endpoint."""
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
