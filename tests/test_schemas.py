"""Unit tests for schema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import FlagCreate, Operator, RuleCreate


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
