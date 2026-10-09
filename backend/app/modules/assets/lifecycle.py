# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Asset lifecycle: which status changes the domain template allows (§B8.1, §B7.3, P8-08).

Pure (no I/O). Statuses, transitions, reasons and conditions all come from the organization's
`assets` template section; nothing about a status is hard-coded here. Conditions are structured
data evaluated by the shared condition evaluator over a fixed field list (`ASSET_FIELDS`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.engines.automation.conditions import evaluate, referenced_fields
from app.modules.assets.config import AssetsConfig, AssetTransition
from app.modules.assets.errors import AssetInvalidTransitionError as AssetInvalidTransition

__all__ = [
    "AssetInvalidTransition",
    "AssetSnapshot",
    "allowed_transitions",
    "check_transition",
    "find_transition",
]


@dataclass(frozen=True)
class AssetSnapshot:
    """The facts about an asset a transition condition may read."""

    status: str
    criticality: str | None = None
    category_code: str | None = None
    holder_type: str | None = None
    holder_id: str | None = None
    custom_fields: Mapping[str, object] = field(default_factory=dict)


def _fields(template: AssetsConfig, snapshot: AssetSnapshot) -> dict[str, object]:
    status = template.status(snapshot.status)
    data: dict[str, object] = {
        "status": snapshot.status,
        "status.category": status.category if status is not None else None,
        "criticality": snapshot.criticality,
        "category.code": snapshot.category_code,
        "category": snapshot.category_code,
        "holder": snapshot.holder_id,
        "holder.type": snapshot.holder_type,
        "holder.is_set": snapshot.holder_type is not None,
    }
    for key, value in snapshot.custom_fields.items():
        data[f"custom.{key}"] = value
    return data


def find_transition(template: AssetsConfig, from_status: str, to_status: str) -> AssetTransition | None:
    """The declared transition between two statuses, or None."""
    return next((t for t in template.transitions if t.from_ == from_status and t.to == to_status), None)


def allowed_transitions(template: AssetsConfig, from_status: str) -> list[AssetTransition]:
    """Every transition the template declares out of `from_status` (conditions not yet checked)."""
    return [t for t in template.transitions if t.from_ == from_status]


def check_transition(
    template: AssetsConfig,
    snapshot: AssetSnapshot,
    to_status: str,
    *,
    reason: str | None,
) -> AssetTransition:
    """Return the transition if the change is allowed; raise `AssetInvalidTransition` otherwise.

    The reason code is one of `unknown_status`, `not_allowed`, `reserved_for_module:<module>`,
    `reason_required`, `condition_failed:<field>`. The caller's permission is checked by the
    service on the loaded record, before this function runs (§C4.3).
    """
    from_status = snapshot.status
    if template.status(from_status) is None or (target := template.status(to_status)) is None:
        raise AssetInvalidTransition(from_status, to_status, "unknown_status")
    if target.set_only_by is not None:
        raise AssetInvalidTransition(from_status, to_status, f"reserved_for_module:{target.set_only_by}")
    transition = find_transition(template, from_status, to_status)
    if transition is None:
        raise AssetInvalidTransition(from_status, to_status, "not_allowed")
    if transition.requires_reason and not (reason and reason.strip()):
        raise AssetInvalidTransition(from_status, to_status, "reason_required")
    data = _fields(template, snapshot)
    for condition in transition.conditions:
        if not evaluate(condition, data):
            names = sorted(referenced_fields(condition))
            raise AssetInvalidTransition(from_status, to_status, f"condition_failed:{names[0]}")
    return transition
