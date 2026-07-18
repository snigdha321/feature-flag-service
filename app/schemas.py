"""Pydantic request/response schemas and validation rules."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")


class Operator(str, Enum):
    """Supported comparison operators for rule matching."""

    EQ = "eq"
    NEQ = "neq"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"


class EvaluationReason(str, Enum):
    """Explains why an evaluation returned its result."""

    FLAG_DISABLED = "FLAG_DISABLED"
    RULE_MATCH = "RULE_MATCH"
    ROLLOUT_IN = "ROLLOUT_IN"
    ROLLOUT_OUT = "ROLLOUT_OUT"
    DEFAULT = "DEFAULT"


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
class RuleBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    priority: int = Field(0, ge=0, description="Lower evaluates first; first match wins")
    attribute: str = Field(..., min_length=1, max_length=128)
    operator: Operator
    values: list[Any] = Field(default_factory=list)
    outcome: bool = True
    rollout_percentage: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _check_values(self) -> RuleBase:
        # Every operator except a pure rollout gate needs at least one operand.
        if not self.values:
            raise ValueError(f"operator '{self.operator.value}' requires 'values'")
        if self.operator in (Operator.EQ, Operator.NEQ) and len(self.values) != 1:
            raise ValueError(f"operator '{self.operator.value}' requires exactly one value")
        return self


class RuleCreate(RuleBase):
    pass


class RuleRead(RuleBase):
    id: int


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------
class FlagBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1024)
    enabled: bool = True
    default_state: bool = False


class FlagCreate(FlagBase):
    key: str = Field(..., min_length=1, max_length=128)
    rules: list[RuleCreate] = Field(default_factory=list)

    @field_validator("key")
    @classmethod
    def _validate_key(cls, v: str) -> str:
        if not KEY_PATTERN.match(v):
            raise ValueError("key must be a slug: lowercase alphanumerics separated by '-' or '_'")
        return v

    @model_validator(mode="after")
    def _unique_priorities(self) -> FlagCreate:
        priorities = [r.priority for r in self.rules]
        if len(priorities) != len(set(priorities)):
            raise ValueError("rule priorities must be unique within a flag")
        return self


class FlagUpdate(BaseModel):
    """All fields optional; rules, when provided, replace the existing set."""

    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1024)
    enabled: bool | None = None
    default_state: bool | None = None
    rules: list[RuleCreate] | None = None

    @model_validator(mode="after")
    def _unique_priorities(self) -> FlagUpdate:
        if self.rules is not None:
            priorities = [r.priority for r in self.rules]
            if len(priorities) != len(set(priorities)):
                raise ValueError("rule priorities must be unique within a flag")
        return self


class FlagRead(FlagBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    rules: list[RuleRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
class EvaluationRequest(BaseModel):
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="User/request attributes, e.g. userId, subscriptionTier, region",
    )


class EvaluationResponse(BaseModel):
    flag_key: str
    enabled: bool
    reason: EvaluationReason
    matched_rule_priority: int | None = None


class BatchEvaluationRequest(EvaluationRequest):
    flag_keys: list[str] = Field(..., min_length=1)


class BatchEvaluationResponse(BaseModel):
    results: list[EvaluationResponse]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
