"""Immutable in-memory representations of flags used by the evaluation hot path.

Snapshots decouple evaluation and caching from the ORM/session lifecycle, so a
cached value is safe to read from any request without touching the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import FeatureFlag
from app.schemas import Operator


@dataclass(frozen=True, slots=True)
class RuleSnapshot:
    priority: int
    attribute: str
    operator: Operator
    values: tuple
    outcome: bool
    rollout_percentage: int | None


@dataclass(frozen=True, slots=True)
class FlagSnapshot:
    key: str
    enabled: bool
    default_state: bool
    rules: tuple[RuleSnapshot, ...] = field(default_factory=tuple)

    @classmethod
    def from_orm(cls, flag: FeatureFlag) -> FlagSnapshot:
        rules = tuple(
            RuleSnapshot(
                priority=r.priority,
                attribute=r.attribute,
                operator=Operator(r.operator),
                values=tuple(r.values or ()),
                outcome=r.outcome,
                rollout_percentage=r.rollout_percentage,
            )
            for r in sorted(flag.rules, key=lambda r: r.priority)
        )
        return cls(
            key=flag.key,
            enabled=flag.enabled,
            default_state=flag.default_state,
            rules=rules,
        )
