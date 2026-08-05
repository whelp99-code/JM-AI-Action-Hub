from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm.exc import StaleDataError

from .api import (
    api_router,
    control_router,
    feature_router,
    focus_router,
    health_router,
    mobile_admin_router,
    mobile_focus_router,
    mobile_public_router,
    mobile_router,
    web_router,
    webhook_router,
)
from .config import Settings, get_settings
from .database import Database

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_directories()
    database = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.create_schema(use_migrations=settings.run_migrations)
        try:
            yield
        finally:
            database.engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="Approval-based closed-loop action control for people, AI workers, and external systems.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.web_dir = Path(__file__).parent / "web"

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Action-Hub-Key", "X-Actor"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = None
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.max_request_body_bytes:
                    response = JSONResponse(status_code=413, content={"detail": "Request body too large"})
            except ValueError:
                response = JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
        if response is None:
            response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
            "form-action 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; worker-src 'self'; manifest-src 'self'",
        )
        if request.url.path.startswith("/api/") or request.url.path == "/share-target":
            response.headers.setdefault("Cache-Control", "no-store")
        if settings.app_env == "production":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.exception_handler(StaleDataError)
    async def concurrent_update_conflict(request: Request, exc: StaleDataError):
        # ActionPlan/ActionItem/FocusSession all use version_id_col=revision for
        # optimistic locking (models.py). Two overlapping writers racing on the
        # same row previously surfaced as an unhandled 500 here -- there was no
        # StaleDataError handling anywhere in the codebase. This is exception
        # mapping only; see docs/IMPROVEMENT_PLAN_V2.md S9 for why a full
        # concurrency redesign is explicitly out of scope.
        logger.warning(
            "Concurrent update conflict: %s %s: %s",
            request.method,
            request.url.path,
            exc,
        )
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "concurrent_update",
                    "message": "This item was changed by another request. Refresh and retry.",
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception):
        logger.error(
            "Unhandled request error: %s %s",
            request.method,
            request.url.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    app.include_router(health_router)
    app.include_router(webhook_router)
    app.include_router(mobile_public_router)
    app.include_router(mobile_admin_router)
    app.include_router(mobile_router)
    app.include_router(mobile_focus_router)
    app.include_router(api_router)
    app.include_router(control_router)
    app.include_router(feature_router)
    app.include_router(focus_router)
    app.mount("/static", StaticFiles(directory=app.state.web_dir), name="static")
    app.include_router(web_router)
    return app


app = create_app()
