# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Which addresses the egress allowlist treats as public (§B6.3 rule 2)."""

from __future__ import annotations

import pytest

from app.channels.egress import is_blocked_address
from app.core.problems import ERROR_REGISTRY, ChannelEgressDeniedError


@pytest.mark.parametrize(
    "address",
    [
        "93.184.216.34",
        "8.8.8.8",
        "1.1.1.1",
        "2606:2800:220:1:248:1893:25c8:1946",
        "2001:4860:4860::8888",
    ],
)
def test_public_unicast_addresses_pass(address: str) -> None:
    assert not is_blocked_address(address)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "127.255.255.254",
        "10.0.0.1",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104
        "224.0.0.1",
        "255.255.255.255",
        "240.0.0.1",
        "198.18.0.1",
        "::1",
        "::",
        "fe80::1",
        "fe80::1%eth0",
        "fc00::1",
        "fd12:3456::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "::ffff:169.254.169.254",
        "2002:7f00:0001::1",
        "64:ff9b::7f00:1",
        "64:ff9b::a00:1",
    ],
)
def test_internal_and_reserved_addresses_are_blocked(address: str) -> None:
    assert is_blocked_address(address)


@pytest.mark.parametrize("value", ["", "not-an-address", "999.1.1.1", "1.2.3", "[::1]"])
def test_anything_that_is_not_an_address_is_blocked(value: str) -> None:
    assert is_blocked_address(value)


def test_the_error_is_registered_and_carries_no_destination() -> None:
    assert ChannelEgressDeniedError in ERROR_REGISTRY
    error = ChannelEgressDeniedError()
    assert error.code == "channel.egress_denied"
    assert "127" not in error.default_detail
