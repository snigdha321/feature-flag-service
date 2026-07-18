"""Unit tests for the evaluation engine."""

from __future__ import annotations

from app.domain import FlagSnapshot, RuleSnapshot
from app.evaluation import evaluate
from app.schemas import EvaluationReason, Operator


def _rule(**kwargs) -> RuleSnapshot:
    defaults = {
        "priority": 0,
        "attribute": "subscriptionTier",
        "operator": Operator.EQ,
        "values": ("premium",),
        "outcome": True,
        "rollout_percentage": None,
    }
    defaults.update(kwargs)
    return RuleSnapshot(**defaults)


def _flag(rules=(), enabled=True, default_state=False) -> FlagSnapshot:
    return FlagSnapshot(
        key="my-flag", enabled=enabled, default_state=default_state, rules=tuple(rules)
    )


def test_disabled_flag_returns_off():
    result = evaluate(_flag(enabled=False, default_state=True), {})
    assert result.enabled is False
    assert result.reason is EvaluationReason.FLAG_DISABLED


def test_default_state_when_no_rule_matches():
    flag = _flag(rules=[_rule()], default_state=True)
    result = evaluate(flag, {"subscriptionTier": "free"})
    assert result.enabled is True
    assert result.reason is EvaluationReason.DEFAULT


def test_eq_rule_match():
    result = evaluate(_flag(rules=[_rule()]), {"subscriptionTier": "premium"})
    assert result.enabled is True
    assert result.reason is EvaluationReason.RULE_MATCH
    assert result.matched_rule_priority == 0


def test_in_operator():
    rule = _rule(attribute="region", operator=Operator.IN, values=("EU", "US"))
    assert evaluate(_flag(rules=[rule]), {"region": "EU"}).enabled is True
    assert evaluate(_flag(rules=[rule]), {"region": "APAC"}).reason is (EvaluationReason.DEFAULT)


def test_neq_and_not_in_operators():
    neq = _rule(operator=Operator.NEQ, values=("free",))
    assert evaluate(_flag(rules=[neq]), {"subscriptionTier": "premium"}).enabled

    not_in = _rule(attribute="region", operator=Operator.NOT_IN, values=("CN",), outcome=True)
    assert evaluate(_flag(rules=[not_in]), {"region": "EU"}).enabled


def test_contains_operator():
    rule = _rule(attribute="email", operator=Operator.CONTAINS, values=("@corp.com",))
    assert evaluate(_flag(rules=[rule]), {"email": "a@corp.com"}).enabled
    assert not evaluate(_flag(rules=[rule]), {"email": "a@gmail.com"}).enabled


def test_first_matching_rule_wins_by_priority():
    r1 = _rule(priority=0, attribute="region", operator=Operator.EQ, values=("EU",), outcome=False)
    r2 = _rule(priority=1, attribute="subscriptionTier", values=("premium",), outcome=True)
    flag = _flag(rules=[r1, r2])
    result = evaluate(flag, {"region": "EU", "subscriptionTier": "premium"})
    assert result.enabled is False
    assert result.matched_rule_priority == 0


def test_missing_attribute_does_not_match():
    result = evaluate(_flag(rules=[_rule()], default_state=False), {})
    assert result.reason is EvaluationReason.DEFAULT
