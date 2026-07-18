"""End-to-end smoke test against a *running* instance.

This is the pytest counterpart of ``scripts/smoke_test.sh``: it exercises the
full feature-flag flow over real HTTP against a live server rather than the
in-process ASGI app used by the rest of the suite.

Target is ``SMOKE_BASE_URL`` (or ``BASE_URL``), defaulting to
``http://localhost:8000``. When no server is reachable the test is skipped, so
it stays harmless during a normal ``make test`` run and only does real work
when a server is up. Run it explicitly with::

    pytest -m smoke                 # server must already be running
    SMOKE_BASE_URL=https://... pytest -m smoke
"""

from __future__ import annotations

import os

import httpx
import pytest
import pytest_asyncio

BASE_URL = os.getenv("SMOKE_BASE_URL") or os.getenv("BASE_URL") or "http://localhost:8000"
KEY = "smoke-checkout"

pytestmark = [pytest.mark.asyncio, pytest.mark.smoke]


@pytest_asyncio.fixture
async def smoke_client():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        try:
            await client.get("/health")
        except httpx.ConnectError:
            pytest.skip(f"no server reachable at {BASE_URL}")
        # Remove any leftover flag from a previous run (ignore result).
        await client.delete(f"/flags/{KEY}")
        try:
            yield client
        finally:
            await client.delete(f"/flags/{KEY}")


async def test_smoke_flow(smoke_client: httpx.AsyncClient):
    health = await smoke_client.get("/health")
    assert health.status_code == 200, health.text

    ready = await smoke_client.get("/ready")
    assert ready.status_code == 200, f"database not reachable: {ready.text}"

    created = await smoke_client.post(
        "/flags",
        json={
            "key": KEY,
            "name": "Smoke Checkout",
            "enabled": True,
            "default_state": False,
            "rules": [
                {
                    "priority": 0,
                    "attribute": "subscriptionTier",
                    "operator": "eq",
                    "values": ["premium"],
                    "outcome": True,
                }
            ],
        },
    )
    assert created.status_code == 201, created.text

    got = await smoke_client.get(f"/flags/{KEY}")
    assert got.status_code == 200, got.text

    matched = await smoke_client.post(
        f"/flags/{KEY}/evaluate",
        json={"context": {"userId": "u-1", "subscriptionTier": "premium"}},
    )
    assert matched.status_code == 200, matched.text
    assert matched.json()["reason"] == "RULE_MATCH", matched.text

    default = await smoke_client.post(
        f"/flags/{KEY}/evaluate",
        json={"context": {"userId": "u-2", "subscriptionTier": "free"}},
    )
    assert default.status_code == 200, default.text
    assert default.json()["reason"] == "DEFAULT", default.text

    deleted = await smoke_client.delete(f"/flags/{KEY}")
    assert deleted.status_code == 204, deleted.text
