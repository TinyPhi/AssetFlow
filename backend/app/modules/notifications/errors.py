# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Errors of the notification channel administration (§B6.3, §B10, §C4.5)."""

from __future__ import annotations

from typing import ClassVar

from app.core.problems import ConflictError, ProblemError

__all__ = [
    "ChannelAlreadyInstalledError",
    "ChannelNotFoundError",
    "ChannelVersionConflictError",
    "DeliveryNotDeadLetteredError",
    "PreferenceLockedError",
    "PreferenceVersionConflictError",
]


class ChannelAlreadyInstalledError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "notification_channel.exists"
    title: ClassVar[str] = "Channel already installed"
    default_detail: ClassVar[str] = "This channel is already installed for the organization."
    description: ClassVar[str] = "An organization has one installation per channel key."


class ChannelNotFoundError(ProblemError):
    status_code = 404
    code: ClassVar[str] = "notification_channel.not_found"
    title: ClassVar[str] = "Channel not found"
    default_detail: ClassVar[str] = "There is no such notification channel."
    description: ClassVar[str] = "No channel with this key is available on this installation."


class ChannelVersionConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "notification_channel.version_conflict"
    title: ClassVar[str] = "Channel version conflict"
    default_detail: ClassVar[str] = "The channel installation was modified by another request."
    description: ClassVar[str] = "The provided version does not match the current version."


class DeliveryNotDeadLetteredError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "notification_delivery.not_dead_lettered"
    title: ClassVar[str] = "Delivery is not dead-lettered"
    default_detail: ClassVar[str] = "Only a dead-lettered delivery can be re-queued."
    description: ClassVar[str] = "Re-queue applies to deliveries whose status is `dead_lettered`."


class PreferenceLockedError(ProblemError):
    status_code = 422
    code: ClassVar[str] = "notification.preference_locked"
    title: ClassVar[str] = "Preference is locked"
    default_detail: ClassVar[str] = "The in-app notice cannot be switched off for this event."
    description: ClassVar[str] = (
        "An automation rule marks this event's notice mandatory (§B6.3 rule 7), so the in-app channel "
        "stays on for it."
    )


class PreferenceVersionConflictError(ConflictError):
    status_code = 409
    code: ClassVar[str] = "notification_preference.version_conflict"
    title: ClassVar[str] = "Preference version conflict"
    default_detail: ClassVar[str] = "The preference was changed elsewhere; reload and try again."
    description: ClassVar[str] = "The provided version does not match the stored preference's version."
