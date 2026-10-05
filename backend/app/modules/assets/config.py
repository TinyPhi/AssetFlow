# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The `assets` section of a domain template (`config/domains/*.yaml`): §B7.3, §B7.4, §B5.4, §B8.1.

Everything an organization decides about its assets lives here as data: tag format, statuses with
their categories, transitions, categories with custom fields, criticality levels, public scan
fields, the public report switch, acknowledgement timings and the two behavior rules. Nothing is
hard-coded per industry (§C12), and no status is a database enum (§C1.4).

Two steps, both pure (no I/O):

* the Pydantic models parse the shape (strict, unknown keys refused);
* `validate_assets_section` adds the cross-reference checks (§B7.4) and reports every problem with
  its exact path, for example `assets.statuses[3].category: unknown category "gone"`.

Transitions are stored as structured data only (`field`, operator, value; §B7.3). They are
evaluated by P8-08 with a small asset-only checker that the workflow engine (M3.1) replaces.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.engines.automation.conditions import referenced_fields
from app.engines.automation.models import Condition

__all__ = [
    "ASSET_FIELDS",
    "PUBLIC_SCAN_FIELDS_ALLOWED",
    "STATUS_CATEGORIES",
    "AcknowledgementConfig",
    "AssetCategory",
    "AssetStatus",
    "AssetTransition",
    "AssetsConfig",
    "CustomField",
    "TagConfig",
    "parse_assets_section",
    "validate_assets_section",
]

#: Status categories (§B7.3): what a status means for availability. `ended` ends custody.
STATUS_CATEGORIES: tuple[str, ...] = ("available", "in_use", "unavailable", "ended")

#: Every asset field a transition condition may read (§B8.1); `custom.<key>` reads a custom field.
ASSET_FIELDS: frozenset[str] = frozenset(
    {
        "tag",
        "name",
        "category",
        "model",
        "manufacturer",
        "serial_number",
        "owner_org_unit",
        "location",
        "holder",
        "status",
        "criticality",
        "purchase_date",
        "purchase_cost",
        "supplier",
        "warranty_end",
    }
)

#: The fixed set an anonymous scan may show (§B11.3, §C5.2). Never the holder (personal data) and
#: never an encrypted custom field; a non-encrypted custom field is named `custom.<key>`.
PUBLIC_SCAN_FIELDS_ALLOWED: frozenset[str] = frozenset(
    {
        "tag",
        "name",
        "category",
        "model",
        "manufacturer",
        "status",
        "criticality",
        "owner_org_unit",
        "location",
    }
)

#: Fields that hold personal data (§C5.2): refused in `public_scan_fields` with a specific message.
_PERSONAL_FIELDS: frozenset[str] = frozenset({"holder"})

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{0,9}$")
_SEPARATORS = frozenset({"-", "_", ".", "/"})
_SELECT_TYPES = frozenset({"select", "multi_select"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TagConfig(_Strict):
    """`assets.tag`: tag = prefix + separator + zero-padded number (§B8.1, M2.1-T3)."""

    prefix: str
    digits: int = Field(ge=3, le=12)
    separator: str = ""

    @field_validator("prefix")
    @classmethod
    def _prefix_shape(cls, value: str) -> str:
        if not _PREFIX_RE.match(value):
            raise ValueError(
                "prefix must be 1-10 characters: capital letters and digits, starting with a letter"
            )
        return value

    @field_validator("separator")
    @classmethod
    def _separator_shape(cls, value: str) -> str:
        if value and value not in _SEPARATORS:
            raise ValueError("separator must be empty or one of - _ . /")
        return value


class AssetStatus(_Strict):
    """One status: a config key, a label and a category (§B7.3)."""

    key: str
    label: str = Field(min_length=1)
    category: str
    is_final: bool | None = None
    is_assignable: bool | None = None
    set_only_by: str | None = None

    @field_validator("key", "set_only_by")
    @classmethod
    def _key_shape(cls, value: str | None) -> str | None:
        if value is not None and not _KEY_RE.match(value):
            raise ValueError("must be lowercase letters, digits and underscores, starting with a letter")
        return value

    @property
    def final(self) -> bool:
        """Terminal statuses end custody; default: every `ended` status."""
        return self.category == "ended" if self.is_final is None else self.is_final

    @property
    def assignable(self) -> bool:
        """Assignable unless ended (AssetManager rule: all minus terminal), unless overridden."""
        return self.category != "ended" if self.is_assignable is None else self.is_assignable


class AssetTransition(_Strict):
    """An allowed move between two statuses. Every condition must hold (structured data only)."""

    from_: str = Field(alias="from")
    to: str
    permission: str | None = None
    requires_reason: bool = False
    conditions: list[Condition] = []


class CustomField(_Strict):
    """A custom field definition of a category (§B8.1)."""

    key: str
    label: str = Field(min_length=1)
    type: Literal["text", "number", "date", "boolean", "select", "multi_select", "json"]
    required: bool = False
    min: float | None = None
    max: float | None = None
    regex: str | None = None
    options: list[str] = []
    is_unique: bool = False
    is_encrypted: bool = False

    @field_validator("key")
    @classmethod
    def _key_shape(cls, value: str) -> str:
        if not _KEY_RE.match(value):
            raise ValueError("must be lowercase letters, digits and underscores, starting with a letter")
        return value

    @model_validator(mode="after")
    def _rules(self) -> CustomField:
        if self.type in _SELECT_TYPES:
            if not self.options:
                raise ValueError(f"a {self.type} field needs at least one option")
            if len(set(self.options)) != len(self.options):
                raise ValueError("options must be unique")
        elif self.options:
            raise ValueError(f"options are only allowed on select and multi_select fields, not {self.type}")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"min {self.min:g} is greater than max {self.max:g}")
        if self.regex is not None:
            if self.type != "text":
                raise ValueError("regex is only allowed on text fields")
            try:
                re.compile(self.regex)
            except re.error as exc:
                raise ValueError(f"regex does not compile: {exc}") from exc
        if self.is_unique and self.is_encrypted:
            raise ValueError("an encrypted field cannot be unique (encrypted values cannot be compared)")
        return self


class AssetCategory(_Strict):
    """One category of the tree (§B8.1): its defaults and its custom fields."""

    code: str
    label: str = Field(min_length=1)
    parent_code: str | None = None
    default_criticality: str | None = None
    responsible_team_code: str | None = None
    tag_prefix: str | None = None
    custom_fields: list[CustomField] = []

    @field_validator("code", "parent_code", "responsible_team_code")
    @classmethod
    def _code_shape(cls, value: str | None) -> str | None:
        if value is not None and not _KEY_RE.match(value):
            raise ValueError("must be lowercase letters, digits and underscores, starting with a letter")
        return value

    @field_validator("tag_prefix")
    @classmethod
    def _tag_prefix_shape(cls, value: str | None) -> str | None:
        if value is not None and not _PREFIX_RE.match(value):
            raise ValueError(
                "tag_prefix must be 1-10 characters: capital letters and digits, starting with a letter"
            )
        return value


class AcknowledgementConfig(_Strict):
    """`assets.acknowledgement`: custody confirmations with reminder and escalation (UF4)."""

    required: bool = False
    remind_after_hours: int | None = Field(default=None, gt=0)
    escalate_after_hours: int | None = Field(default=None, gt=0)
    auto_close_after_days: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _order(self) -> AcknowledgementConfig:
        if (
            self.remind_after_hours is not None
            and self.escalate_after_hours is not None
            and self.escalate_after_hours <= self.remind_after_hours
        ):
            raise ValueError("escalate_after_hours must be greater than remind_after_hours")
        return self


class AssetsConfig(_Strict):
    """The whole `assets` section."""

    tag: TagConfig
    statuses: list[AssetStatus] = Field(min_length=1)
    initial: str
    transitions: list[AssetTransition] = []
    criticality: list[str] = Field(
        default_factory=lambda: ["low", "medium", "high", "critical"], min_length=1
    )
    categories: list[AssetCategory] = []
    public_scan_fields: list[str] = []
    public_report: bool = False
    acknowledgement: AcknowledgementConfig = AcknowledgementConfig()
    owner_follows_holder: bool = True
    cascade_on_member_move: Literal["on", "off", "ask"] = "ask"

    @field_validator("cascade_on_member_move", mode="before")
    @classmethod
    def _yaml_booleans(cls, value: object) -> object:
        # YAML 1.1 reads a bare `on` / `off` as a boolean; accept that spelling too.
        if value is True:
            return "on"
        if value is False:
            return "off"
        return value

    def status(self, key: str) -> AssetStatus | None:
        """The status with this key, or None."""
        return next((s for s in self.statuses if s.key == key), None)

    def category(self, code: str) -> AssetCategory | None:
        """The category with this code, or None."""
        return next((c for c in self.categories if c.code == code), None)


def _path(loc: tuple[int | str, ...]) -> str:
    out = "assets"
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else f".{part}"
    return out


def _message(msg: str) -> str:
    return msg.removeprefix("Value error, ")


def parse_assets_section(raw: object) -> AssetsConfig:
    """Parse `raw` (the YAML value of `assets`) into the models; raises `ValidationError`."""
    return AssetsConfig.model_validate(raw)


def validate_assets_section(raw: object, *, known_permissions: Collection[str]) -> list[str]:
    """Every problem in the `assets` section, one string each (`assets.<path>: <message>`); empty when valid.

    `known_permissions` is the set of permissions the modules declare (§B7.4); a transition may name
    only one of those.
    """
    if not isinstance(raw, Mapping):
        return ["assets: must be a mapping"]
    try:
        config = parse_assets_section(raw)
    except ValidationError as exc:
        return [f"{_path(err['loc'])}: {_message(err['msg'])}" for err in exc.errors()]
    return _cross_check(config, known_permissions=set(known_permissions))


def _cross_check(config: AssetsConfig, *, known_permissions: set[str]) -> list[str]:
    problems: list[str] = []
    problems += _check_statuses(config)
    problems += _check_transitions(config, known_permissions)
    problems += _check_categories(config)
    problems += _check_public_scan_fields(config)
    return problems


def _duplicates(values: list[str]) -> set[str]:
    return {v for v in values if values.count(v) > 1}


def _check_statuses(config: AssetsConfig) -> list[str]:
    problems: list[str] = []
    duplicated = _duplicates([s.key for s in config.statuses])
    for index, status in enumerate(config.statuses):
        if status.key in duplicated:
            problems.append(f"assets.statuses[{index}].key: duplicate status {status.key!r}")
        if status.category not in STATUS_CATEGORIES:
            problems.append(f'assets.statuses[{index}].category: unknown category "{status.category}"')
    initial = config.status(config.initial)
    if initial is None:
        problems.append(f'assets.initial: unknown status "{config.initial}"')
    elif initial.final:
        problems.append(
            f'assets.initial: status "{config.initial}" is final and cannot be the initial status'
        )
    return problems


def _custom_field_keys(config: AssetsConfig) -> set[str]:
    return {f.key for c in config.categories for f in c.custom_fields if not f.is_encrypted}


def _check_transitions(config: AssetsConfig, known_permissions: set[str]) -> list[str]:
    problems: list[str] = []
    statuses = {s.key for s in config.statuses}
    allowed_fields = ASSET_FIELDS | {f"custom.{key}" for key in _custom_field_keys(config)}
    seen: set[tuple[str, str]] = set()
    for index, transition in enumerate(config.transitions):
        base = f"assets.transitions[{index}]"
        if transition.from_ not in statuses:
            problems.append(f'{base}.from: unknown status "{transition.from_}"')
        if transition.to not in statuses:
            problems.append(f'{base}.to: unknown status "{transition.to}"')
        if transition.from_ == transition.to:
            problems.append(f"{base}.to: a transition must change the status")
        if (transition.from_, transition.to) in seen:
            problems.append(f'{base}: duplicate transition "{transition.from_}" -> "{transition.to}"')
        seen.add((transition.from_, transition.to))
        if transition.permission is not None and transition.permission not in known_permissions:
            problems.append(f'{base}.permission: unknown permission "{transition.permission}"')
        for cond_index, condition in enumerate(transition.conditions):
            for field_name in sorted(referenced_fields(condition)):
                if field_name not in allowed_fields:
                    problems.append(
                        f'{base}.conditions[{cond_index}].field: unknown asset field "{field_name}"'
                    )
    return problems


def _check_categories(config: AssetsConfig) -> list[str]:
    problems: list[str] = []
    codes = [c.code for c in config.categories]
    duplicated = _duplicates(codes)
    known = set(codes)
    for index, category in enumerate(config.categories):
        base = f"assets.categories[{index}]"
        if category.code in duplicated:
            problems.append(f"{base}.code: duplicate category {category.code!r}")
        if category.parent_code is not None and category.parent_code not in known:
            problems.append(f'{base}.parent_code: unknown category "{category.parent_code}"')
        if (
            category.default_criticality is not None
            and category.default_criticality not in config.criticality
        ):
            problems.append(
                f'{base}.default_criticality: unknown criticality "{category.default_criticality}"'
            )
        keys = [f.key for f in category.custom_fields]
        for field_index, field in enumerate(category.custom_fields):
            if keys.count(field.key) > 1:
                problems.append(f"{base}.custom_fields[{field_index}].key: duplicate field {field.key!r}")
    if _duplicates(config.criticality):
        problems.append("assets.criticality: levels must be unique")
    problems += _check_parent_cycles(config)
    return problems


def _check_parent_cycles(config: AssetsConfig) -> list[str]:
    parents = {c.code: c.parent_code for c in config.categories}
    problems: list[str] = []
    for index, category in enumerate(config.categories):
        seen = {category.code}
        current = category.parent_code
        while current is not None and current in parents:
            if current in seen:
                problems.append(f"assets.categories[{index}].parent_code: category tree has a cycle")
                break
            seen.add(current)
            current = parents[current]
    return problems


def _check_public_scan_fields(config: AssetsConfig) -> list[str]:
    problems: list[str] = []
    encrypted = {f.key for c in config.categories for f in c.custom_fields if f.is_encrypted}
    plain = _custom_field_keys(config) - encrypted
    for index, name in enumerate(config.public_scan_fields):
        path = f"assets.public_scan_fields[{index}]"
        if name in _PERSONAL_FIELDS:
            problems.append(f'{path}: field "{name}" is personal data and cannot be public')
        elif name.startswith("custom."):
            key = name.removeprefix("custom.")
            if key in encrypted and key not in plain:
                problems.append(f'{path}: field "{name}" is encrypted and cannot be public')
            elif key not in plain:
                problems.append(f'{path}: unknown custom field "{name}"')
        elif name not in PUBLIC_SCAN_FIELDS_ALLOWED:
            problems.append(f'{path}: field "{name}" is not an allowed public field')
    if _duplicates(config.public_scan_fields):
        problems.append("assets.public_scan_fields: fields must be unique")
    return problems
