"""Process-local TTL cache for flag snapshots.

The evaluation hot path reads through this cache so it never issues a database
query per request. Entries expire after a configurable TTL and are explicitly
invalidated whenever a flag is created, updated, or deleted.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from app.domain import FlagSnapshot
from app.telemetry import CACHE_EVENTS


class FlagCache:
    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.RLock()
        # key -> (snapshot, expires_at)
        self._store: dict[str, tuple[FlagSnapshot, float]] = {}

    def get(self, key: str) -> FlagSnapshot | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                CACHE_EVENTS.labels(event="miss").inc()
                return None
            snapshot, expires_at = entry
            if self._clock() >= expires_at:
                # Expired; drop it and treat as a miss.
                del self._store[key]
                CACHE_EVENTS.labels(event="expired").inc()
                return None
            CACHE_EVENTS.labels(event="hit").inc()
            return snapshot

    def set(self, snapshot: FlagSnapshot) -> None:
        with self._lock:
            self._store[snapshot.key] = (snapshot, self._clock() + self._ttl)

    def invalidate(self, key: str) -> None:
        with self._lock:
            if self._store.pop(key, None) is not None:
                CACHE_EVENTS.labels(event="invalidate").inc()

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


_cache: FlagCache | None = None


def init_cache(ttl_seconds: float) -> FlagCache:
    global _cache
    _cache = FlagCache(ttl_seconds=ttl_seconds)
    return _cache


def get_cache() -> FlagCache:
    if _cache is None:
        raise RuntimeError("cache not initialized; call init_cache() first")
    return _cache
