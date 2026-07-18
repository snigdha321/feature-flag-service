"""Integration tests exercising the full API against a real database."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _create_flag(client, **overrides):
    payload = {
        "key": "new-checkout",
        "name": "New Checkout",
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
    }
    payload.update(overrides)
    return await client.post("/flags", json=payload)


async def test_health_and_ready(app_client):
    assert (await app_client.get("/health")).json() == {"status": "ok"}
    ready = await app_client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


async def test_create_and_get_flag(app_client):
    resp = await _create_flag(app_client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["key"] == "new-checkout"
    assert len(body["rules"]) == 1

    got = await app_client.get("/flags/new-checkout")
    assert got.status_code == 200
    assert got.json()["name"] == "New Checkout"


async def test_duplicate_key_conflict(app_client):
    await _create_flag(app_client)
    dup = await _create_flag(app_client)
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "conflict"


async def test_get_unknown_flag_404(app_client):
    resp = await app_client.get("/flags/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_invalid_key_422(app_client):
    resp = await _create_flag(app_client, key="Invalid Key")
    assert resp.status_code == 422


async def test_list_flags(app_client):
    await _create_flag(app_client)
    await _create_flag(app_client, key="dark-mode", name="Dark Mode")
    resp = await app_client.get("/flags")
    assert resp.status_code == 200
    keys = {f["key"] for f in resp.json()}
    assert {"new-checkout", "dark-mode"} <= keys


async def test_evaluate_rule_match_and_default(app_client):
    await _create_flag(app_client)

    on = await app_client.post(
        "/flags/new-checkout/evaluate",
        json={"context": {"subscriptionTier": "premium"}},
    )
    assert on.status_code == 200
    assert on.json() == {
        "flag_key": "new-checkout",
        "enabled": True,
        "reason": "RULE_MATCH",
        "matched_rule_priority": 0,
    }

    off = await app_client.post(
        "/flags/new-checkout/evaluate",
        json={"context": {"subscriptionTier": "free"}},
    )
    assert off.json()["enabled"] is False
    assert off.json()["reason"] == "DEFAULT"


async def test_disabled_flag_evaluates_off(app_client):
    await _create_flag(app_client, enabled=False, default_state=True)
    resp = await app_client.post(
        "/flags/new-checkout/evaluate",
        json={"context": {"subscriptionTier": "premium"}},
    )
    assert resp.json()["reason"] == "FLAG_DISABLED"
    assert resp.json()["enabled"] is False


async def test_update_invalidates_cache(app_client):
    await _create_flag(app_client)
    # Prime cache with an evaluation.
    first = await app_client.post(
        "/flags/new-checkout/evaluate",
        json={"context": {"subscriptionTier": "premium"}},
    )
    assert first.json()["enabled"] is True

    # Disable the flag; the cached snapshot must be invalidated.
    upd = await app_client.put("/flags/new-checkout", json={"enabled": False})
    assert upd.status_code == 200

    after = await app_client.post(
        "/flags/new-checkout/evaluate",
        json={"context": {"subscriptionTier": "premium"}},
    )
    assert after.json()["reason"] == "FLAG_DISABLED"


async def test_delete_flag(app_client):
    await _create_flag(app_client)
    resp = await app_client.delete("/flags/new-checkout")
    assert resp.status_code == 204
    assert (await app_client.get("/flags/new-checkout")).status_code == 404


async def test_percentage_rollout_endpoint(app_client):
    await _create_flag(
        app_client,
        key="beta-feature",
        name="Beta",
        rules=[
            {
                "priority": 0,
                "attribute": "region",
                "operator": "eq",
                "values": ["EU"],
                "outcome": True,
                "rollout_percentage": 100,
            }
        ],
    )
    resp = await app_client.post(
        "/flags/beta-feature/evaluate",
        json={"context": {"region": "EU", "userId": "user-1"}},
    )
    assert resp.json()["enabled"] is True
    assert resp.json()["reason"] == "ROLLOUT_IN"


async def test_batch_evaluation(app_client):
    await _create_flag(app_client)
    resp = await app_client.post(
        "/evaluate/batch",
        json={
            "flag_keys": ["new-checkout", "missing-flag"],
            "context": {"subscriptionTier": "premium"},
        },
    )
    assert resp.status_code == 200
    results = {r["flag_key"]: r for r in resp.json()["results"]}
    assert results["new-checkout"]["enabled"] is True
    assert results["missing-flag"]["enabled"] is False


async def test_metrics_endpoint(app_client):
    resp = await app_client.get("/metrics")
    assert resp.status_code == 200
    assert "feature_flag_evaluations_total" in resp.text
