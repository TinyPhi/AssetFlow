# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Automation rule models: event -> condition -> notify action (§B7.3, §B7.4, M1.5-T2).

A rule reads ``when`` an event happens, ``if`` a structured condition holds, ``then`` notify these
recipients on these channels. Conditions are structured data, never free text or ``eval`` (§B7.3).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

__all__ = [
    "AllCondition",
    "AnyCondition",
    "AutomationRule",
    "Condition",
    "FieldCondition",
    "NotifyAction",
    "RecipientRef",
]

_FIELD_OPERATORS = frozenset({"equals", "not_equals", "in", "not_in", "lt", "lte", "gt", "gte", "exists"})

#: §B6.3 recipient keywords this plan (M1.5-T2) does not yet resolve; a later module registers them.
_NOT_YET_AVAILABLE = frozenset({"assignee", "requester", "team_lead", "org_unit_manager"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldCondition(_Strict):
    """One structured condition: a registered field, an operator, a value (§B7.3)."""

    field: str
    operator: Literal["equals", "not_equals", "in", "not_in", "lt", "lte", "gt", "gte", "exists"]
    value: Any = None


class AllCondition(_Strict):
    """True only if every nested condition is true."""

    all: list[Condition]


class AnyCondition(_Strict):
    """True if any nested condition is true."""

    any: list[Condition]


Condition = FieldCondition | AllCondition | AnyCondition
AllCondition.model_rebuild()
AnyCondition.model_rebuild()


class RecipientRef(_Strict):
    """A parsed recipient keyword (§B6.3): ``holder``, ``actor``, ``team:<field>`` or
    ``role:<role>@<scope>`` where scope is ``organization``, ``org_unit:<field>`` or ``team:<field>``.
    """

    kind: Literal["holder", "actor", "team", "role"]
    team_field: str | None = None
    role_key: str | None = None
    scope: Literal["organization", "org_unit", "team"] | None = None
    scope_field: str | None = None

    @classmethod
    def parse(cls, raw: str) -> RecipientRef:
        if raw == "holder":
            return cls(kind="holder")
        if raw == "actor":
            return cls(kind="actor")
        if raw.startswith("team:"):
            return cls(kind="team", team_field=raw.removeprefix("team:"))
        if raw.startswith("role:"):
            role_part, _, scope_part = raw.removeprefix("role:").partition("@")
            if not role_part or not scope_part:
                raise ValueError(f"recipient {raw!r}: expected 'role:<role>@<scope>'")
            if scope_part == "organization":
                return cls(kind="role", role_key=role_part, scope="organization")
            if scope_part.startswith("org_unit:"):
                return cls(
                    kind="role",
                    role_key=role_part,
                    scope="org_unit",
                    scope_field=scope_part.removeprefix("org_unit:"),
                )
            if scope_part.startswith("team:"):
                return cls(
                    kind="role",
                    role_key=role_part,
                    scope="team",
                    scope_field=scope_part.removeprefix("team:"),
                )
            raise ValueError(f"recipient {raw!r}: unknown scope {scope_part!r}")
        if raw in _NOT_YET_AVAILABLE:
            raise ValueError(f"recipient {raw!r} is not available yet")
        raise ValueError(f"recipient {raw!r}: unknown recipient keyword")


def _parse_recipient(value: object) -> object:
    return RecipientRef.parse(value) if isinstance(value, str) else value


ParsedRecipientRef = Annotated[RecipientRef, BeforeValidator(_parse_recipient)]


class NotifyAction(_Strict):
    """``then``: notify these recipients, on these channels, with this template (§B6.3)."""

    recipients: list[ParsedRecipientRef] = Field(min_length=1)
    channels: list[str] = Field(min_length=1)
    template: str
    mandatory: bool = False


class AutomationRule(_Strict):
    """One ``automations`` entry of a domain template (§B7.3)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    when: str
    if_: Condition | None = Field(default=None, alias="if")
    then: NotifyAction
