# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""SecretsProvider interface (§B6.1, §B6.2), INTERFACE_VERSION 1.0.

References use ``secret://<area>/<name>#<key>`` (§C1.6). A missing or unreadable secret raises
``app.core.problems.SecretsUnavailableError``; an implementation never returns a default value.
Implementations pass the shared suite in ``tests/contract/secrets/``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class SecretsProvider(ABC):
    """Secrets provider: key/value reads plus transit-style encryption."""

    INTERFACE_VERSION: str = "1.0"

    @property
    def name(self) -> str:
        """Provider implementation identifier."""
        return self.__class__.__name__

    @abstractmethod
    async def get(self, ref: str) -> str:
        """Return the value of ``secret://<area>/<name>#<key>``."""

    @abstractmethod
    async def get_map(self, path: str) -> dict[str, str]:
        """Return every key of ``secret://<area>/<name>`` as a mapping."""

    @abstractmethod
    async def encrypt(self, context: str, plaintext: str) -> str:
        """Encrypt ``plaintext`` bound to ``context`` (for example the organization id)."""

    @abstractmethod
    async def decrypt(self, context: str, ciphertext: str) -> str:
        """Decrypt a value produced by :meth:`encrypt` with the same ``context``."""

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        """Return ``{"status": ...}`` without secret values or filesystem paths."""


class SecretDecryptionError(ValueError):
    """A ciphertext could not be decrypted. Deliberately generic: no reason, context or data."""

    def __init__(self) -> None:
        super().__init__("The value could not be decrypted.")
