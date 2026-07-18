"""Tests for the service landing route."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_root_landing(app_client):
    resp = await app_client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["docs"] == "/docs"
    assert body["health"] == "/health"
    assert "version" in body
