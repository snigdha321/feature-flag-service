"""FastAPI application factory and wiring."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app import __version__
from app.cache import init_cache
from app.config import get_settings
from app.db import dispose_engine, init_engine
from app.errors import register_exception_handlers
from app.logging_config import configure_logging, get_logger, request_id_var
from app.routers import evaluation, flags, health
from app.telemetry import setup_tracing

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    init_engine(settings)
    init_cache(settings.cache_ttl_seconds)
    log.info("startup.complete", env=settings.env, version=__version__)
    try:
        yield
    finally:
        # Graceful shutdown: dispose DB connections so the pool drains cleanly.
        await dispose_engine()
        log.info("shutdown.complete")


def create_app() -> FastAPI:
    settings = get_settings()
    # Logging is also configured in lifespan, but do it here so import-time
    # logs (and tests using the app factory) are structured too.
    configure_logging(level=settings.log_level, json_logs=settings.log_json)

    app = FastAPI(
        title="Feature Flag Service",
        version=__version__,
        description="Store feature flags and evaluate them against a user context.",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        log.info("request.start", method=request.method, path=request.url.path)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["x-request-id"] = request_id
        return response

    register_exception_handlers(app)
    setup_tracing(app, settings)

    app.include_router(health.router)
    app.include_router(flags.router)
    app.include_router(evaluation.router)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
