# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The only way a channel reaches the network (§B6.3 rule 2, §C5.8 security-sensitive).

A call is allowed only when the URL is HTTPS, its host is on the allowlist (the channel's own
`egress_hosts` plus the installation's `allowed_hosts`), and **every** address the name resolves
to is public. The request then connects to the exact address that passed the check - the URL is
rewritten to that literal address, with `Host` and the TLS server name kept as the original name -
so a DNS answer that changes between the check and the connect cannot reach an internal host.
Every call (and every retry) resolves and checks again; redirects are never followed.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

import httpx

from app.core.problems import ChannelEgressDeniedError

__all__ = ["EgressClient", "Resolver", "is_blocked_address", "system_resolver"]

Resolver = Callable[[str, int], Awaitable[list[str]]]

DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_TOTAL_TIMEOUT = 10.0
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


async def system_resolver(host: str, port: int) -> list[str]:
    """Resolve `host` with the operating system's resolver (A and AAAA)."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def is_blocked_address(address: str) -> bool:
    """True for anything that is not a plain public unicast address.

    Covers private, loopback, link-local, multicast, unspecified, reserved and shared (CGNAT)
    ranges for IPv4 and IPv6, and looks through IPv4-mapped, 6to4 and NAT64 IPv6 addresses to the
    IPv4 address they carry.
    """
    try:
        ip = ipaddress.ip_address(address.split("%", maxsplit=1)[0])
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or ip.sixtofour
        if embedded is None and ip in _NAT64:
            embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if embedded is not None and is_blocked_address(str(embedded)):
            return True
    return not ip.is_global or ip.is_multicast


class EgressClient:
    """An HTTP client that can only reach allowed, public destinations."""

    def __init__(
        self,
        allowed_hosts: Iterable[str],
        *,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
        allow_private_addresses: bool = False,
    ) -> None:
        self._allowed = frozenset(h.strip().lower().rstrip(".") for h in allowed_hosts if h.strip())
        self._resolver = resolver
        self._transport = transport
        self._connect_timeout = connect_timeout
        self._total_timeout = total_timeout
        # Only for the operator's own relay in development and test (a local mail catcher lives on a
        # private address); platform config refuses it in production. The host must still be allowlisted.
        self._allow_private = allow_private_addresses

    def __repr__(self) -> str:
        return f"EgressClient(allowed_hosts={len(self._allowed)})"

    async def resolve_checked(self, host: str, port: int) -> str:
        """Return the first checked address for an allowed `host`."""
        return (await self.resolve_all_checked(host, port))[0]

    async def resolve_all_checked(self, host: str, port: int) -> list[str]:
        """Every address of an allowed `host`, all of which passed the check, in resolver order.

        A caller that opens its own socket (SMTP) tries them in turn, so a name with both an IPv6
        and an IPv4 address still connects when one family is unreachable.
        """
        name = host.strip().lower().rstrip(".")
        if name not in self._allowed:
            raise ChannelEgressDeniedError
        try:
            async with asyncio.timeout(self._total_timeout):
                addresses = await self._resolver(name, port)
        except (OSError, TimeoutError) as exc:
            raise ChannelEgressDeniedError from exc
        if not addresses or (not self._allow_private and any(is_blocked_address(a) for a in addresses)):
            raise ChannelEgressDeniedError
        return addresses

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | str | None = None,
        json: Any = None,
    ) -> httpx.Response:
        """Send one HTTPS request to an allowed host; raises `ChannelEgressDeniedError` otherwise."""
        try:
            target = httpx.URL(url)
        except httpx.InvalidURL as exc:
            raise ChannelEgressDeniedError from exc
        if target.scheme != "https" or target.userinfo or not target.host:
            raise ChannelEgressDeniedError
        port = target.port or 443
        address = await self.resolve_checked(target.host, port)

        name = f"[{target.host}]" if ":" in target.host else target.host
        host_header = name if port == 443 else f"{name}:{port}"
        send_headers = {**(headers or {}), "Host": host_header}
        pinned = target.copy_with(host=address, port=port)
        transport = self._transport or httpx.AsyncHTTPTransport()
        timeout = httpx.Timeout(self._total_timeout, connect=self._connect_timeout)
        async with httpx.AsyncClient(
            transport=transport, follow_redirects=False, timeout=timeout, trust_env=False
        ) as client:
            async with asyncio.timeout(self._total_timeout):
                return await client.request(
                    method,
                    pinned,
                    headers=send_headers,
                    content=content,
                    json=json,
                    extensions={"sni_hostname": target.host},
                )
