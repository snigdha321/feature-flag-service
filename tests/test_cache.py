"""Unit tests for the in-memory TTL cache."""

from __future__ import annotations

from app.cache import FlagCache
from app.domain import FlagSnapshot


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _snapshot(key: str = "my-flag") -> FlagSnapshot:
    return FlagSnapshot(key=key, enabled=True, default_state=False, rules=())


def test_miss_then_hit():
    cache = FlagCache(ttl_seconds=30)
    assert cache.get("my-flag") is None
    cache.set(_snapshot())
    assert cache.get("my-flag") is not None


def test_ttl_expiry():
    clock = FakeClock()
    cache = FlagCache(ttl_seconds=30, clock=clock)
    cache.set(_snapshot())
    clock.advance(29)
    assert cache.get("my-flag") is not None
    clock.advance(2)  # now past TTL
    assert cache.get("my-flag") is None


def test_invalidate():
    cache = FlagCache(ttl_seconds=30)
    cache.set(_snapshot())
    cache.invalidate("my-flag")
    assert cache.get("my-flag") is None


def test_clear():
    cache = FlagCache(ttl_seconds=30)
    cache.set(_snapshot("a"))
    cache.set(_snapshot("b"))
    assert len(cache) == 2
    cache.clear()
    assert len(cache) == 0
