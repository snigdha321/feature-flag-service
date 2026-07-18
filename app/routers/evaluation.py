"""Flag evaluation endpoints (single and batch)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app import service
from app.db import get_session
from app.errors import NotFoundError
from app.schemas import (
    BatchEvaluationRequest,
    BatchEvaluationResponse,
    EvaluationReason,
    EvaluationRequest,
    EvaluationResponse,
)

router = APIRouter(tags=["evaluation"])


@router.post("/flags/{key}/evaluate", response_model=EvaluationResponse)
async def evaluate_flag(
    key: str,
    payload: EvaluationRequest,
    session: AsyncSession = Depends(get_session),
) -> EvaluationResponse:
    return await service.evaluate_flag(session, key, payload.context)


@router.post("/evaluate/batch", response_model=BatchEvaluationResponse)
async def evaluate_batch(
    payload: BatchEvaluationRequest,
    session: AsyncSession = Depends(get_session),
) -> BatchEvaluationResponse:
    results: list[EvaluationResponse] = []
    for key in payload.flag_keys:
        try:
            results.append(await service.evaluate_flag(session, key, payload.context))
        except NotFoundError:
            # Missing flags in a batch resolve to a safe OFF/default rather than
            # failing the whole request.
            results.append(
                EvaluationResponse(
                    flag_key=key,
                    enabled=False,
                    reason=EvaluationReason.DEFAULT,
                )
            )
    return BatchEvaluationResponse(results=results)
