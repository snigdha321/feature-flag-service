"""Application service tying together cache, persistence, and evaluation."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.cache import get_cache
from app.domain import FlagSnapshot
from app.errors import NotFoundError
from app.evaluation import evaluate
from app.schemas import EvaluationResponse
from app.telemetry import EVALUATION_LATENCY, EVALUATIONS_TOTAL


async def load_snapshot(session: AsyncSession, key: str) -> FlagSnapshot:
    """Read-through cache lookup for a flag snapshot."""
    cache = get_cache()
    cached = cache.get(key)
    if cached is not None:
        return cached

    flag = await crud.get_flag(session, key)
    if flag is None:
        raise NotFoundError(f"flag '{key}' not found")

    snapshot = FlagSnapshot.from_orm(flag)
    cache.set(snapshot)
    return snapshot


async def evaluate_flag(
    session: AsyncSession, key: str, context: dict[str, Any]
) -> EvaluationResponse:
    """Evaluate a single flag for the given context, using the cache."""
    with EVALUATION_LATENCY.labels(flag_key=key).time():
        snapshot = await load_snapshot(session, key)
        result = evaluate(snapshot, context)

    EVALUATIONS_TOTAL.labels(
        flag_key=key,
        result="on" if result.enabled else "off",
        reason=result.reason.value,
    ).inc()
    return result


def invalidate(key: str) -> None:
    """Drop a flag from the cache after a write."""
    get_cache().invalidate(key)
