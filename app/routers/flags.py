"""Feature flag CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud, service
from app.db import get_session
from app.schemas import FlagCreate, FlagRead, FlagUpdate

router = APIRouter(prefix="/flags", tags=["flags"])


@router.post("", response_model=FlagRead, status_code=status.HTTP_201_CREATED)
async def create_flag(
    payload: FlagCreate, session: AsyncSession = Depends(get_session)
) -> FlagRead:
    flag = await crud.create_flag(session, payload)
    service.invalidate(flag.key)
    return FlagRead.model_validate(flag)


@router.get("", response_model=list[FlagRead])
async def list_flags(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[FlagRead]:
    flags = await crud.list_flags(session, limit=limit, offset=offset)
    return [FlagRead.model_validate(f) for f in flags]


@router.get("/{key}", response_model=FlagRead)
async def get_flag(key: str, session: AsyncSession = Depends(get_session)) -> FlagRead:
    flag = await crud.get_flag_or_404(session, key)
    return FlagRead.model_validate(flag)


@router.put("/{key}", response_model=FlagRead)
async def update_flag(
    key: str, payload: FlagUpdate, session: AsyncSession = Depends(get_session)
) -> FlagRead:
    flag = await crud.update_flag(session, key, payload)
    service.invalidate(key)
    return FlagRead.model_validate(flag)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flag(key: str, session: AsyncSession = Depends(get_session)) -> None:
    await crud.delete_flag(session, key)
    service.invalidate(key)
