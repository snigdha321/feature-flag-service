"""Shared pytest fixtures.

Integration tests run against ``TEST_DATABASE_URL`` when provided (Postgres in
CI); otherwise they fall back to a disposable per-test SQLite database so the
suite runs anywhere without Docker.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app import cache as cache_module
from app import db as db_module
from app.config import get_settings
from app.models import Base


def _test_database_url(tmp_path) -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        return url
    return f"sqlite+aiosqlite:///{tmp_path / f'test_{uuid.uuid4().hex}.db'}"


@pytest_asyncio.fixture
async def app_client(tmp_path, monkeypatch) -> AsyncIterator[AsyncClient]:
    # Point the app at an isolated test database before settings are read.
    monkeypatch.setenv("DATABASE_URL", _test_database_url(tmp_path))
    monkeypatch.setenv("OTEL_ENABLED", "false")
    monkeypatch.setenv("LOG_JSON", "false")
    get_settings.cache_clear()

    # Reset module-global engine/cache for a clean slate per test.
    db_module._engine = None
    db_module._sessionmaker = None

    from app.main import create_app

    settings = get_settings()
    engine = db_module.init_engine(settings)
    cache_module.init_cache(settings.cache_ttl_seconds)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await db_module.dispose_engine()
    get_settings.cache_clear()
