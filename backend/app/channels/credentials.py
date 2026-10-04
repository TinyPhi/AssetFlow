# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Where a channel's credentials live: OpenBao only, never the database (§B6.3 rule 1, §B11.4).

`write` is for the installation service (the api role has write-only access to the channel path);
`read` is for the channel runtime alone (the worker role). Nothing else may call `read`, and no
value is ever returned to an API caller. The `notification_channels` row keeps only the reference
this module returns.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from uuid import UUID

from app.providers.secrets.base import SecretsProvider

__all__ = ["ChannelCredentialStore", "channel_secret_ref"]


def channel_secret_ref(organization_id: UUID | str, channel_id: UUID | str) -> str:
    """`secret://assetflow/orgs/<organization_id>/channels/<channel_id>`; ids are parsed as UUIDs."""
    return f"secret://assetflow/orgs/{UUID(str(organization_id))}/channels/{UUID(str(channel_id))}"


class ChannelCredentialStore:
    """Writes and reads one installation's credentials through the secrets provider."""

    def __init__(self, provider: SecretsProvider) -> None:
        self._provider = provider

    async def write(
        self, organization_id: UUID | str, channel_id: UUID | str, values: Mapping[str, str]
    ) -> str:
        """Store `values` (replacing any earlier ones) and return the reference to keep."""
        ref = channel_secret_ref(organization_id, channel_id)
        await self._provider.put(ref, values)
        return ref

    async def read(self, secret_ref: str) -> Mapping[str, str]:
        """Runtime only: the stored values as a read-only mapping."""
        return MappingProxyType(await self._provider.get_map(secret_ref))
