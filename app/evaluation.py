"""Contextual flag evaluation engine and deterministic percentage rollout."""

from __future__ import annotations

import hashlib
from typing import Any

from app.domain import FlagSnapshot, RuleSnapshot
from app.schemas import EvaluationReason, EvaluationResponse, Operator

_BUCKETS = 100


def compute_bucket(flag_key: str, identifier: str) -> int:
    """Map (flag_key, identifier) to a stable bucket in ``[0, 100)``.

    Deterministic: the same inputs always yield the same bucket. Including the
    flag key decorrelates rollouts across different flags so a user is not
    always in the "early" cohort everywhere.
    """
    digest = hashlib.sha256(f"{flag_key}:{identifier}".encode()).hexdigest()
    return int(digest, 16) % _BUCKETS


def _match_operator(operator: Operator, actual: Any, values: tuple) -> bool:
    if actual is None:
        return False
    match operator:
        case Operator.EQ:
            return actual == values[0]
        case Operator.NEQ:
            return actual != values[0]
        case Operator.IN:
            return actual in values
        case Operator.NOT_IN:
            return actual not in values
        case Operator.CONTAINS:
            # Substring/membership containment: actual contains any listed value.
            try:
                return any(v in actual for v in values)
            except TypeError:
                return False
    return False


def _rule_matches(rule: RuleSnapshot, context: dict[str, Any]) -> bool:
    return _match_operator(rule.operator, context.get(rule.attribute), rule.values)


def _rollout_identifier(context: dict[str, Any]) -> str | None:
    """Pick a stable identifier for bucketing from common context keys."""
    for key in ("userId", "user_id", "id"):
        value = context.get(key)
        if value is not None:
            return str(value)
    return None


def evaluate(flag: FlagSnapshot, context: dict[str, Any]) -> EvaluationResponse:
    """Evaluate a flag snapshot against a context and explain the result."""
    if not flag.enabled:
        return EvaluationResponse(
            flag_key=flag.key,
            enabled=False,
            reason=EvaluationReason.FLAG_DISABLED,
        )

    for rule in flag.rules:  # already ordered by priority
        if not _rule_matches(rule, context):
            continue

        if rule.rollout_percentage is not None:
            identifier = _rollout_identifier(context)
            # Without an identifier we cannot bucket deterministically -> exclude.
            in_rollout = (
                identifier is not None
                and compute_bucket(flag.key, identifier) < rule.rollout_percentage
            )
            if in_rollout:
                return EvaluationResponse(
                    flag_key=flag.key,
                    enabled=rule.outcome,
                    reason=EvaluationReason.ROLLOUT_IN,
                    matched_rule_priority=rule.priority,
                )
            return EvaluationResponse(
                flag_key=flag.key,
                enabled=not rule.outcome,
                reason=EvaluationReason.ROLLOUT_OUT,
                matched_rule_priority=rule.priority,
            )

        return EvaluationResponse(
            flag_key=flag.key,
            enabled=rule.outcome,
            reason=EvaluationReason.RULE_MATCH,
            matched_rule_priority=rule.priority,
        )

    return EvaluationResponse(
        flag_key=flag.key,
        enabled=flag.default_state,
        reason=EvaluationReason.DEFAULT,
    )
