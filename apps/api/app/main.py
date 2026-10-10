"""FastAPI application factory and endpoints."""

import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.db import get_engine, get_session
from app.routers import (
    admin_audit,
    admin_users,
    auth,
    baseline,
    ingestion,
    miss_reports,
    platform_dashboard,
    platform_documents,
    platform_jobs,
    platform_sources,
    provisions,
    resolve,
    review_tasks,
    search,
)
from app.settings import get_settings


# Configure JSON logging
class JSONFormatter(logging.Formatter):
    """Custom formatter that outputs JSON-formatted logs."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        return json.dumps(log_data)


def setup_logging(level: str) -> None:
    """Set up structured JSON logging."""
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logger = logging.getLogger()
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:  # noqa: ANN401
    """Lifespan context manager for startup and shutdown."""
    setup_logging(get_settings().log_level)
    logging.getLogger().info("Application started")
    yield
    logging.getLogger().info("Application shutting down")
    engine = get_engine()
    await engine.dispose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title="TaxResearch API",
        version=__version__,
        lifespan=lifespan,
    )

    # CORS middleware
    cors_origins = settings.get_cors_origins_list()
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Request ID middleware
    @app.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: Any,  # noqa: ANN401
    ) -> Response:
        """Add request ID to request context and response headers."""
        # Get or generate request ID
        incoming_request_id = request.headers.get("x-request-id")
        if incoming_request_id:
            # Validate incoming request ID: alphanumeric, dots, underscores, hyphens, max 64 chars
            if re.match(r"^[A-Za-z0-9._-]{1,64}$", incoming_request_id):
                request_id = incoming_request_id
            else:
                # Invalid format, generate a new one
                request_id = str(uuid.uuid4())
        else:
            # No incoming request ID, generate one
            request_id = str(uuid.uuid4())

        # Store request ID in request state
        request.state.request_id = request_id

        # Measure request time
        start_time = time.time()
        response = await call_next(request)
        latency_ms = (time.time() - start_time) * 1000

        # Add request ID to response headers
        response.headers["X-Request-Id"] = request_id

        # Log structured request info
        logger = logging.getLogger()
        log_data = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "latency_ms": f"{latency_ms:.2f}",
        }
        logger.info(json.dumps(log_data))

        return response  # type: ignore[no-any-return]

    # Ready endpoint: returns 503 if database is unavailable
    @app.get("/ready")
    async def ready(session: AsyncSession = Depends(get_session)) -> dict[str, str]:  # noqa: B008
        """Readiness check endpoint. Returns 503 if database is unreachable."""
        try:
            # Try a simple SELECT 1 query
            await session.execute(text("SELECT 1"))
            return {"status": "ready"}
        except Exception:
            raise HTTPException(status_code=503, detail={"status": "unavailable"}) from None

    # Health endpoint
    @app.get("/health")
    async def health(session: AsyncSession = Depends(get_session)) -> dict[str, str]:  # noqa: B008
        """Health check endpoint."""
        try:
            # Try a simple SELECT 1 query
            await session.execute(text("SELECT 1"))
            return {"status": "ok", "database": "ok"}
        except Exception:
            # Database is unavailable
            return {"status": "degraded", "database": "unavailable"}

    # Version endpoint
    @app.get("/v1/version")
    async def version(
        session: AsyncSession = Depends(get_session),  # noqa: B008
    ) -> dict[str, Any | None]:
        """Get API version and corpus version."""
        corpus_version: int | None = None
        try:
            # Try to get max corpus_version ID
            result = await session.execute(text("SELECT MAX(id) FROM corpus_versions"))
            row = result.scalar()
            if row is not None:
                corpus_version = int(row)
        except Exception:
            # corpus_versions table doesn't exist or is empty
            pass

        return {
            "version": __version__,
            "corpus_version": corpus_version,
        }

    app.include_router(auth.router)
    app.include_router(admin_users.router)
    app.include_router(admin_audit.router)
    app.include_router(baseline.router)
    app.include_router(ingestion.router)
    app.include_router(platform_documents.router)
    app.include_router(platform_sources.router)
    app.include_router(platform_jobs.router)
    app.include_router(platform_dashboard.router)
    app.include_router(miss_reports.router)
    app.include_router(provisions.router)
    app.include_router(resolve.router)
    app.include_router(review_tasks.router)
    app.include_router(search.router)

    return app


# Module-level app instance will be created lazily via uvicorn --factory
# if DATABASE_URL is not available at import time.
try:
    app = create_app()
except Exception:
    # If we can't create the app (e.g., DATABASE_URL not set),
    # don't create it at import time. Uvicorn will use --factory instead.
    app = None  # type: ignore[assignment]
