"""Application service tying together cache, persistence, and evaluation."""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud
from app.cache import get_cache
from app.config import get_settings
from app.domain import FlagSnapshot
from app.errors import NotFoundError
from app.evaluation import evaluate
from app.logging_config import get_logger
from app.schemas import EvaluationReason, EvaluationResponse
from app.telemetry import (
    CACHE_EVENTS,
    EVALUATION_FALLBACKS_TOTAL,
    EVALUATION_LATENCY,
    EVALUATIONS_TOTAL,
)

log = get_logger(__name__)


async def load_snapshot(session: AsyncSession, key: str) -> FlagSnapshot:
    """Read-through cache lookup for a flag snapshot."""
    cache = get_cache()
    cached = cache.get(key)
    if cached is not None:
        log.info("snapshot.load", flag_key=key, source="cache")
        return cached

    flag = await crud.get_flag(session, key)
    if flag is None:
        raise NotFoundError(f"flag '{key}' not found")

    snapshot = FlagSnapshot.from_orm(flag)
    cache.set(snapshot)
    log.info("snapshot.load", flag_key=key, source="db")
    return snapshot


async def evaluate_flag(
    session: AsyncSession, key: str, context: dict[str, Any]
) -> EvaluationResponse:
    """Evaluate a single flag for the given context, using the cache.

    If the database is unavailable, the evaluation degrades gracefully rather
    than erroring: a still-cached (possibly stale) snapshot is used when present,
    otherwise the configured safe default state is returned.
    """
    with EVALUATION_LATENCY.labels(flag_key=key).time():
        try:
            snapshot = await load_snapshot(session, key)
        except SQLAlchemyError as exc:
            result = _degraded_evaluation(key, context, exc)
        else:
            result = evaluate(snapshot, context)

    EVALUATIONS_TOTAL.labels(
        flag_key=key,
        result="on" if result.enabled else "off",
        reason=result.reason.value,
    ).inc()
    return result


def _degraded_evaluation(key: str, context: dict[str, Any], exc: Exception) -> EvaluationResponse:
    """Produce a result when the database is unavailable."""
    stale = get_cache().get_stale(key)
    if stale is not None:
        log.warning("evaluation.degraded.stale_cache", flag_key=key, error=str(exc))
        CACHE_EVENTS.labels(event="stale").inc()
        EVALUATION_FALLBACKS_TOTAL.labels(source="stale_cache").inc()
        return evaluate(stale, context)

    fallback = get_settings().evaluation_fallback_enabled
    log.warning(
        "evaluation.degraded.default",
        flag_key=key,
        fallback_enabled=fallback,
        error=str(exc),
    )
    EVALUATION_FALLBACKS_TOTAL.labels(source="default").inc()
    return EvaluationResponse(
        flag_key=key,
        enabled=fallback,
        reason=EvaluationReason.DEFAULT,
    )


def invalidate(key: str) -> None:
    """Drop a flag from the cache after a write."""
    get_cache().invalidate(key)
