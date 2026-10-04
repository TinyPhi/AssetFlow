# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Registration of the channels the contract suite runs against (§C8.4).

A channel plan adds its channel with ``@contract_target("<key>")`` on a zero-argument factory; the
shared checks in ``test_channel_contract.py`` then run for it automatically.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from app.channels.base import NotificationChannel
from app.channels.inapp import InAppChannel
from app.core.db import Connection

ORG = "0192f000-0000-7000-8000-0000000000a1"
PUBLIC_ADDRESS = "93.184.216.34"

TARGETS: dict[str, Callable[[], NotificationChannel]] = {}


def contract_target(
    key: str,
) -> Callable[[Callable[[], NotificationChannel]], Callable[[], NotificationChannel]]:
    """Register `factory` as the way to build the channel with this `key`."""

    def register(factory: Callable[[], NotificationChannel]) -> Callable[[], NotificationChannel]:
        if key in TARGETS:
            raise ValueError(f"contract target {key!r} is already registered")
        TARGETS[key] = factory
        return factory

    return register


@contract_target("inapp")
def _inapp() -> NotificationChannel:
    # health and the class-level declarations never touch the connection.
    return InAppChannel(cast(Connection, None))
