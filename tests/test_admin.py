"""Tests for the landing route and the token-gated admin endpoints."""

from __future__ import annotations

import pytest

from app.config import get_settings

pytestmark = pytest.mark.asyncio

ADMIN_TOKEN = "s3cret-token"


def _configure_token(monkeypatch, token: str | None) -> None:
    if token is None:
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    else:
        monkeypatch.setenv("ADMIN_TOKEN", token)
    get_settings.cache_clear()


async def test_root_landing(app_client):
    resp = await app_client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["docs"] == "/docs"
    assert body["health"] == "/health"
    assert "version" in body


async def test_admin_cache_disabled_without_token_config(app_client, monkeypatch):
    _configure_token(monkeypatch, None)
    resp = await app_client.get("/admin/cache")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "http_error"


async def test_admin_cache_requires_valid_token(app_client, monkeypatch):
    _configure_token(monkeypatch, ADMIN_TOKEN)

    missing = await app_client.get("/admin/cache")
    assert missing.status_code == 401

    wrong = await app_client.get("/admin/cache", headers={"x-admin-token": "nope"})
    assert wrong.status_code == 401

    ok = await app_client.get("/admin/cache", headers={"x-admin-token": ADMIN_TOKEN})
    assert ok.status_code == 200


async def test_admin_cache_reports_entries(app_client, monkeypatch):
    _configure_token(monkeypatch, ADMIN_TOKEN)
    headers = {"x-admin-token": ADMIN_TOKEN}

    empty = (await app_client.get("/admin/cache", headers=headers)).json()
    assert empty["size"] == 0
    assert empty["entries"] == []

    await app_client.post(
        "/flags",
        json={
            "key": "admin-demo",
            "name": "Admin Demo",
            "enabled": True,
            "default_state": False,
            "rules": [],
        },
    )
    # Populate the cache via a read-through evaluation.
    await app_client.post("/flags/admin-demo/evaluate", json={"context": {"userId": "u-1"}})

    state = (await app_client.get("/admin/cache", headers=headers)).json()
    assert state["size"] == 1
    entry = state["entries"][0]
    assert entry["key"] == "admin-demo"
    assert entry["enabled"] is True
    assert entry["expired"] is False
    assert entry["expires_in_seconds"] > 0
