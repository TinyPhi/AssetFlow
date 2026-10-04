# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Builds the one-call `ChannelContext` a channel's `send` receives (§B6.3 rules 1-2).

The runtime is the only reader of channel credentials, and the only creator of the egress client
a channel may use. A context lives for one send: it is never cached, and its `repr` never shows a
credential value.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from app.channels.base import ChannelContext, NotificationChannel
from app.channels.credentials import ChannelCredentialStore
from app.channels.egress import EgressClient

__all__ = ["ChannelRuntime"]


class ChannelRuntime:
    """Supplies each send with its credentials and an allowlisted HTTP client."""

    def __init__(
        self,
        store: ChannelCredentialStore,
        *,
        egress_factory: Callable[[list[str]], EgressClient] = EgressClient,
    ) -> None:
        self._store = store
        self._egress_factory = egress_factory

    async def build_context(
        self, channel: NotificationChannel, organization_id: str, installation: Mapping[str, Any]
    ) -> ChannelContext:
        """Context for one send of `channel` under `installation` (a `notification_channels` row)."""
        credentials: Mapping[str, str] = {}
        secret_ref = installation.get("secret_ref")
        if channel.secret_fields and secret_ref:
            credentials = await self._store.read(str(secret_ref))
        hosts = [*channel.egress_hosts, *(installation.get("allowed_hosts") or [])]
        return ChannelContext(
            organization_id=organization_id,
            installation=dict(installation),
            credentials=MappingProxyType(dict(credentials)),
            http=self._egress_factory(hosts) if hosts else None,
        )
