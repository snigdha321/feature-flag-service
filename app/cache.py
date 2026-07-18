"""Process-local TTL cache for flag snapshots.

The evaluation hot path reads through this cache so it never issues a database
query per request. Entries expire after a configurable TTL and are explicitly
invalidated whenever a flag is created, updated, or deleted.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

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
                # Expired: treat as a miss, but retain the entry so it can serve
                # as a stale fallback if the database is unavailable. It will be
                # overwritten on the next successful load or dropped on invalidate.
                CACHE_EVENTS.labels(event="expired").inc()
                return None
            CACHE_EVENTS.labels(event="hit").inc()
            return snapshot

    def get_stale(self, key: str) -> FlagSnapshot | None:
        """Return a cached snapshot ignoring TTL, for degraded-mode fallback."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            return entry[0]

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

    def describe(self) -> dict[str, Any]:
        """Return a JSON-serializable view of the cache for introspection.

        Reports the configured TTL, the number of entries, and per-entry
        metadata (key, remaining TTL, whether it is expired-but-retained, and a
        summary of the cached snapshot). Reads are non-mutating: expired entries
        are reported, not evicted.
        """
        now = self._clock()
        with self._lock:
            entries = [
                {
                    "key": key,
                    "enabled": snapshot.enabled,
                    "default_state": snapshot.default_state,
                    "rules": len(snapshot.rules),
                    "expires_in_seconds": round(expires_at - now, 3),
                    "expired": now >= expires_at,
                }
                for key, (snapshot, expires_at) in self._store.items()
            ]
        entries.sort(key=lambda entry: str(entry["key"]))
        return {"ttl_seconds": self._ttl, "size": len(entries), "entries": entries}

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
