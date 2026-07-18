"""Data-access layer for feature flags and their rules."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ConflictError, NotFoundError
from app.models import FeatureFlag, FlagRule
from app.schemas import FlagCreate, FlagUpdate, RuleCreate


def _build_rule(rule: RuleCreate) -> FlagRule:
    return FlagRule(
        priority=rule.priority,
        attribute=rule.attribute,
        operator=rule.operator.value,
        values=list(rule.values),
        outcome=rule.outcome,
        rollout_percentage=rule.rollout_percentage,
    )


async def get_flag(session: AsyncSession, key: str) -> FeatureFlag | None:
    result = await session.execute(select(FeatureFlag).where(FeatureFlag.key == key))
    return result.scalar_one_or_none()


async def get_flag_or_404(session: AsyncSession, key: str) -> FeatureFlag:
    flag = await get_flag(session, key)
    if flag is None:
        raise NotFoundError(f"flag '{key}' not found")
    return flag


async def list_flags(session: AsyncSession, limit: int = 100, offset: int = 0) -> list[FeatureFlag]:
    result = await session.execute(
        select(FeatureFlag).order_by(FeatureFlag.key).limit(limit).offset(offset)
    )
    return list(result.scalars().all())


async def create_flag(session: AsyncSession, data: FlagCreate) -> FeatureFlag:
    flag = FeatureFlag(
        key=data.key,
        name=data.name,
        description=data.description,
        enabled=data.enabled,
        default_state=data.default_state,
        rules=[_build_rule(r) for r in data.rules],
    )
    session.add(flag)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(f"flag '{data.key}' already exists") from exc
    await session.refresh(flag)
    return flag


async def update_flag(session: AsyncSession, key: str, data: FlagUpdate) -> FeatureFlag:
    flag = await get_flag_or_404(session, key)

    if data.name is not None:
        flag.name = data.name
    if data.description is not None:
        flag.description = data.description
    if data.enabled is not None:
        flag.enabled = data.enabled
    if data.default_state is not None:
        flag.default_state = data.default_state

    if data.rules is not None:
        # Replace the full rule set for a predictable, idempotent update.
        await session.execute(delete(FlagRule).where(FlagRule.flag_id == flag.id))
        flag.rules = [_build_rule(r) for r in data.rules]

    await session.commit()
    await session.refresh(flag)
    return flag


async def delete_flag(session: AsyncSession, key: str) -> None:
    flag = await get_flag_or_404(session, key)
    await session.delete(flag)
    await session.commit()
