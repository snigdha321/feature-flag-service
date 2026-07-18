"""Unit tests for deterministic percentage rollout."""

from __future__ import annotations

from app.domain import FlagSnapshot, RuleSnapshot
from app.evaluation import compute_bucket, evaluate
from app.schemas import EvaluationReason, Operator


def test_bucket_is_deterministic():
    assert compute_bucket("flag-a", "user-123") == compute_bucket("flag-a", "user-123")


def test_bucket_in_range():
    for i in range(1000):
        assert 0 <= compute_bucket("flag", f"user-{i}") < 100


def test_bucket_decorrelated_across_flags():
    # Different flag keys should not produce identical bucket assignments.
    a = [compute_bucket("flag-a", f"user-{i}") for i in range(500)]
    b = [compute_bucket("flag-b", f"user-{i}") for i in range(500)]
    assert a != b


def test_rollout_distribution_is_approximately_correct():
    percentage = 30
    n = 20000
    included = sum(1 for i in range(n) if compute_bucket("checkout", f"user-{i}") < percentage)
    ratio = included / n
    assert abs(ratio - percentage / 100) < 0.02


def _rollout_flag(percentage: int) -> FlagSnapshot:
    rule = RuleSnapshot(
        priority=0,
        attribute="region",
        operator=Operator.EQ,
        values=("EU",),
        outcome=True,
        rollout_percentage=percentage,
    )
    return FlagSnapshot(key="checkout", enabled=True, default_state=False, rules=(rule,))


def test_rollout_stable_for_same_user():
    flag = _rollout_flag(50)
    ctx = {"region": "EU", "userId": "user-777"}
    first = evaluate(flag, ctx)
    for _ in range(10):
        assert evaluate(flag, ctx).enabled == first.enabled
    assert first.reason in (EvaluationReason.ROLLOUT_IN, EvaluationReason.ROLLOUT_OUT)


def test_rollout_zero_excludes_everyone():
    flag = _rollout_flag(0)
    for i in range(200):
        result = evaluate(flag, {"region": "EU", "userId": f"user-{i}"})
        assert result.enabled is False
        assert result.reason is EvaluationReason.ROLLOUT_OUT


def test_rollout_hundred_includes_everyone():
    flag = _rollout_flag(100)
    for i in range(200):
        result = evaluate(flag, {"region": "EU", "userId": f"user-{i}"})
        assert result.enabled is True
        assert result.reason is EvaluationReason.ROLLOUT_IN


def test_rollout_without_identifier_is_excluded():
    flag = _rollout_flag(100)
    result = evaluate(flag, {"region": "EU"})  # no userId
    assert result.enabled is False
    assert result.reason is EvaluationReason.ROLLOUT_OUT
