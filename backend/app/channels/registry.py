# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Built-in and third-party notification channels (§B6.3 rule 9).

A third-party channel package registers an entry point in the ``assetflow.channels`` group
(matching the provider pattern, §B6.1 rule 7); duplicate keys are refused at boot, the same as a
duplicate provider type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import entry_points

from app.channels.base import NotificationChannel
from app.channels.email import EmailChannel
from app.channels.inapp import InAppChannel
from app.channels.webhook import WebhookChannel
from app.core.config import AppConfig

__all__ = ["ChannelRegistry", "default_registry"]

ENTRY_POINT_GROUP = "assetflow.channels"


@dataclass
class ChannelRegistry:
    """Channel key -> implementation class."""

    _by_key: dict[str, type[NotificationChannel]] = field(default_factory=dict)

    def register(self, channel_class: type[NotificationChannel]) -> None:
        """Register `channel_class` under its own `key`."""
        key = channel_class.key
        if key in self._by_key:
            raise ValueError(f"channel {key!r} is already registered")
        self._by_key[key] = channel_class

    def get(self, key: str) -> type[NotificationChannel] | None:
        """Return the class registered for `key`, or None."""
        return self._by_key.get(key)

    def keys(self) -> list[str]:
        """Every registered channel key."""
        return list(self._by_key)


def default_registry(cfg: AppConfig | None = None) -> ChannelRegistry:
    """Built-in channels plus any `assetflow.channels` entry points found on this installation.

    `email` is offered only when the platform config enables the SMTP relay.
    """
    registry = ChannelRegistry()
    registry.register(InAppChannel)
    registry.register(WebhookChannel)
    if cfg is not None and cfg.notifications.channels.email.enabled:
        registry.register(EmailChannel)
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        registry.register(entry_point.load())
    return registry
