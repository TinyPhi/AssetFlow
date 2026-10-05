# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Component error classes (§C1.5.1, §C4.5, M2.1-T6, P8-09)."""

from __future__ import annotations

from typing import ClassVar

from app.core.problems import ConflictError, NotFoundError, PermissionDeniedError

__all__ = [
    "ComponentAlreadyAttachedError",
    "ComponentChildEndedError",
    "ComponentCycleError",
    "ComponentNotAttachedError",
    "ScopeDeniedError",
]


class ComponentAlreadyAttachedError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "asset_component.already_attached"
    title: ClassVar[str] = "Asset already attached"
    default_detail: ClassVar[str] = "This asset is already a component of a parent asset. Detach it first."
    description: ClassVar[str] = (
        "An asset has at most one current parent. Detach the child from its current parent, then "
        "attach it again."
    )


class ComponentCycleError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "asset_component.cycle"
    title: ClassVar[str] = "Component cycle refused"
    default_detail: ClassVar[str] = "An asset cannot be attached to itself or to one of its own components."
    description: ClassVar[str] = (
        "Attaching this child would make an asset its own ancestor. The parent chain is walked "
        "inside the transaction and the attach is refused when the child is already above the parent."
    )


class ComponentChildEndedError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "asset_component.child_ended"
    title: ClassVar[str] = "Ended asset cannot be attached"
    default_detail: ClassVar[str] = "An asset in an ended status cannot be attached as a component."
    description: ClassVar[str] = (
        "The child's status belongs to the `ended` status category of the organization's domain template."
    )


class ComponentNotAttachedError(NotFoundError):
    status_code = 404
    code: ClassVar[str] = "asset_component.not_attached"
    title: ClassVar[str] = "Component not attached"
    default_detail: ClassVar[str] = "This asset is not a current component of the given parent."
    description: ClassVar[str] = "There is no current attachment between the two assets."


class ScopeDeniedError(PermissionDeniedError):
    """A write refused because part of it falls outside the caller's scope (§C4.5, §C5.4 rule 5).

    Names the count of out-of-scope records, never their ids."""

    status_code = 403
    code: ClassVar[str] = "scope.denied"
    title: ClassVar[str] = "Outside your scope"
    default_detail: ClassVar[str] = "The action covers records outside your scope."
    description: ClassVar[str] = (
        "A write needs permission on every record it touches; at least one record is outside the "
        "caller's scope, so nothing was changed."
    )

    def __init__(self, count: int | None = None) -> None:
        detail = None if count is None else f"{count} record(s) are outside your scope; nothing was changed."
        super().__init__(detail)
