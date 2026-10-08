# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Builds the one-call `ChannelContext` a channel's `send` receives (§B6.3 rules 1-2).

The runtime is the only reader of channel credentials, and the only creator of the egress client
a channel may use. A context lives for one send: it is never cached, and its `repr` never shows a
credential value. Credentials come from two places: the installation's own secret reference
(per-organization channel secrets) and `secret://` references in the platform config, for settings
that belong to the whole installation (for example the SMTP relay's password).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any

from app.channels.base import ChannelContext, NotificationChannel, RecipientResolver
from app.channels.credentials import ChannelCredentialStore
from app.channels.egress import EgressClient
from app.core.config import is_secret_ref

__all__ = ["ChannelRuntime"]


def _default_egress(hosts: list[str], allow_private: bool) -> EgressClient:
    return EgressClient(hosts, allow_private_addresses=allow_private)


class ChannelRuntime:
    """Supplies each send with its credentials and an allowlisted HTTP client."""

    def __init__(
        self,
        store: ChannelCredentialStore,
        *,
        egress_factory: Callable[[list[str], bool], EgressClient] = _default_egress,
    ) -> None:
        self._store = store
        self._egress_factory = egress_factory

    async def build_context(
        self,
        channel: NotificationChannel,
        organization_id: str,
        installation: Mapping[str, Any],
        *,
        platform: Mapping[str, Any] | None = None,
        recipients: RecipientResolver | None = None,
    ) -> ChannelContext:
        """Context for one send of `channel` under `installation` (a `notification_channels` row)."""
        platform_settings = dict(platform or {})
        credentials: dict[str, str] = {}
        secret_ref = installation.get("secret_ref")
        if channel.secret_fields and secret_ref:
            credentials.update(await self._store.read(str(secret_ref)))
        for name in channel.platform_secret_fields:
            ref = platform_settings.get(name)
            if isinstance(ref, str) and is_secret_ref(ref):
                credentials[name] = await self._store.read_ref(ref)
        hosts = [*channel.egress_allowlist(platform_settings), *(installation.get("allowed_hosts") or [])]
        allow_private = bool(platform_settings.get("allow_private_addresses", False))
        return ChannelContext(
            organization_id=organization_id,
            installation=dict(installation),
            credentials=MappingProxyType(credentials),
            http=self._egress_factory(hosts, allow_private) if hosts else None,
            platform={k: v for k, v in platform_settings.items() if k not in channel.platform_secret_fields},
            recipients=recipients,
        )
