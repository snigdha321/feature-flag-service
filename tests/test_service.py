"""Unit tests for the service layer: graceful DB-unavailable fallback and
cache invalidation, exercised without a real database."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app import service
from app.cache import FlagCache
from app.domain import FlagSnapshot, RuleSnapshot
from app.schemas import EvaluationReason, Operator

pytestmark = pytest.mark.asyncio


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _snapshot(key: str = "new-checkout") -> FlagSnapshot:
    rule = RuleSnapshot(
        priority=0,
        attribute="subscriptionTier",
        operator=Operator.EQ,
        values=("premium",),
        outcome=True,
        rollout_percentage=None,
    )
    return FlagSnapshot(key=key, enabled=True, default_state=False, rules=(rule,))


def _use_cache(monkeypatch, cache: FlagCache) -> None:
    monkeypatch.setattr(service, "get_cache", lambda: cache)


def _db_down(monkeypatch) -> None:
    async def _raise(_session, _key):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(service.crud, "get_flag", _raise)


async def test_db_unavailable_falls_back_to_default(monkeypatch):
    _use_cache(monkeypatch, FlagCache(ttl_seconds=30))
    _db_down(monkeypatch)

    result = await service.evaluate_flag(None, "new-checkout", {"userId": "u-1"})

    assert result.reason is EvaluationReason.DEFAULT
    assert result.enabled is False  # configured safe default is OFF


async def test_db_unavailable_serves_stale_cache(monkeypatch):
    clock = FakeClock()
    cache = FlagCache(ttl_seconds=30, clock=clock)
    cache.set(_snapshot())
    clock.advance(60)  # entry is now expired (a normal read would miss)
    _use_cache(monkeypatch, cache)
    _db_down(monkeypatch)

    result = await service.evaluate_flag(None, "new-checkout", {"subscriptionTier": "premium"})

    assert result.reason is EvaluationReason.RULE_MATCH
    assert result.enabled is True


async def test_not_found_still_raises_when_db_is_up(monkeypatch):
    _use_cache(monkeypatch, FlagCache(ttl_seconds=30))

    async def _missing(_session, _key):
        return None

    monkeypatch.setattr(service.crud, "get_flag", _missing)

    from app.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await service.evaluate_flag(None, "missing", {})


async def test_invalidate_drops_cached_snapshot(monkeypatch):
    cache = FlagCache(ttl_seconds=30)
    cache.set(_snapshot())
    _use_cache(monkeypatch, cache)

    service.invalidate("new-checkout")

    assert cache.get("new-checkout") is None
