# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The events the notification code itself publishes to the outbox (§B9.3, §C7.2 "New event type").

Each is written with its audit event in the same transaction as the change it describes. They are
documented in the generated events reference (`docs/reference/events.md`); a test fails when one is
published without being listed here. They are not available to automation rules (the automation
registry knows only the events of the modules that opted in).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["NOTIFICATION_EVENTS", "PublishedEvent"]


@dataclass(frozen=True)
class PublishedEvent:
    """One published event type: what it means and the exact keys of its payload."""

    description: str
    fields: tuple[str, ...]
    aggregate_type: str


_CHANNEL = (
    "id",
    "channel_key",
    "display_name",
    "settings",
    "enabled",
    "allowed_hosts",
    "allow_personal_data",
)

NOTIFICATION_EVENTS: dict[str, PublishedEvent] = {
    "notification.read": PublishedEvent(
        "A member marked one of their notices read.", ("id",), "notification"
    ),
    "notification.read_all": PublishedEvent(
        "A member marked all their unread notices read.", ("count",), "notification"
    ),
    "notification_channel.installed": PublishedEvent(
        "An admin installed a channel. Secret values are never in the payload, only the names that are set.",
        (*_CHANNEL, "version", "secret_fields_set", "secrets_changed"),
        "notification_channel",
    ),
    "notification_channel.updated": PublishedEvent(
        "An admin changed a channel installation.",
        (*_CHANNEL, "version", "secret_fields_set", "secrets_changed"),
        "notification_channel",
    ),
    "notification_channel.disabled": PublishedEvent(
        "An admin (or the platform admin) switched a channel off: the kill switch.",
        (*_CHANNEL, "version", "secret_fields_set"),
        "notification_channel",
    ),
    "notification_channel.enabled": PublishedEvent(
        "A channel was switched back on.", (*_CHANNEL, "version", "secret_fields_set"), "notification_channel"
    ),
    "notification_delivery.dead_lettered": PublishedEvent(
        "A delivery used its last attempt or failed in a way retrying cannot fix.",
        ("delivery_id", "channel_key", "error_code", "attempts"),
        "notification_delivery",
    ),
    "notification_delivery.requeued": PublishedEvent(
        "An admin sent a dead-lettered delivery again.",
        ("status", "attempts", "channel_key"),
        "notification_delivery",
    ),
    "notification_preferences.changed": PublishedEvent(
        "A member changed their notification preferences.", ("member_id", "changes"), "member"
    ),
}
