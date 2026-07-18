"""Unit tests for schema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import EvaluationRequest, FlagCreate, Operator, RuleCreate


def test_valid_flag():
    flag = FlagCreate(key="new-checkout", name="New Checkout")
    assert flag.key == "new-checkout"


@pytest.mark.parametrize("bad_key", ["New Checkout", "UPPER", "has space", "-leading", "trailing-"])
def test_invalid_slug_key(bad_key: str):
    with pytest.raises(ValidationError):
        FlagCreate(key=bad_key, name="x")


def test_rollout_percentage_bounds():
    with pytest.raises(ValidationError):
        RuleCreate(attribute="region", operator=Operator.EQ, values=["EU"], rollout_percentage=101)


def test_eq_requires_single_value():
    with pytest.raises(ValidationError):
        RuleCreate(attribute="region", operator=Operator.EQ, values=["EU", "US"])


def test_operator_requires_values():
    with pytest.raises(ValidationError):
        RuleCreate(attribute="region", operator=Operator.IN, values=[])


def test_duplicate_priorities_rejected():
    with pytest.raises(ValidationError):
        FlagCreate(
            key="f",
            name="f",
            rules=[
                RuleCreate(priority=0, attribute="a", operator=Operator.EQ, values=["x"]),
                RuleCreate(priority=0, attribute="b", operator=Operator.EQ, values=["y"]),
            ],
        )


# ---------------------------------------------------------------------------
# Evaluation context payload validation
# ---------------------------------------------------------------------------
def test_context_accepts_scalars_and_lists():
    req = EvaluationRequest(
        context={"userId": "u-1", "age": 30, "beta": True, "regions": ["EU", "US"]}
    )
    assert req.context["userId"] == "u-1"
    assert req.context["regions"] == ["EU", "US"]


def test_context_defaults_to_empty():
    assert EvaluationRequest().context == {}


def test_context_rejects_nested_object():
    with pytest.raises(ValidationError):
        EvaluationRequest(context={"user": {"id": "u-1"}})


def test_context_rejects_non_scalar_list_items():
    with pytest.raises(ValidationError):
        EvaluationRequest(context={"tags": [{"x": 1}]})


def test_context_rejects_too_many_attributes():
    with pytest.raises(ValidationError):
        EvaluationRequest(context={f"k{i}": i for i in range(200)})


def test_context_rejects_oversized_string_value():
    with pytest.raises(ValidationError):
        EvaluationRequest(context={"note": "x" * 5000})
