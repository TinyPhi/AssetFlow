# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""SecretsProvider interface (§B6.1, §B6.2), INTERFACE_VERSION 1.1.

References use ``secret://<area>/<name>#<key>`` (§C1.6). A missing or unreadable secret raises
``app.core.problems.SecretsUnavailableError``; an implementation never returns a default value.
Implementations pass the shared suite in ``tests/contract/secrets/``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any


class SecretsProvider(ABC):
    """Secrets provider: key/value reads plus transit-style encryption."""

    INTERFACE_VERSION: str = "1.1"

    @property
    def name(self) -> str:
        """Provider implementation identifier."""
        return self.__class__.__name__

    async def aclose(self) -> None:  # noqa: B027 - optional hook with a no-op default
        """Release held resources (connections, clients). The default holds none."""

    @abstractmethod
    async def get(self, ref: str) -> str:
        """Return the value of ``secret://<area>/<name>#<key>``."""

    @abstractmethod
    async def get_map(self, path: str) -> dict[str, str]:
        """Return every key of ``secret://<area>/<name>`` as a mapping."""

    async def put(self, path: str, values: Mapping[str, str]) -> None:
        """Replace every key of ``secret://<area>/<name>`` with ``values`` (added in 1.1).

        Optional: a provider written against 1.0 keeps working and simply cannot store secrets.
        """
        raise NotImplementedError(f"{self.name} does not support writing secrets.")

    async def patch(self, path: str, values: Mapping[str, str | None]) -> None:
        """Change only the given keys of ``secret://<area>/<name>``; a ``None`` value removes its key.

        Added in 1.1 beside :meth:`put`, for a writer that may not read the secret back (it cannot
        read-modify-write). The secret must already exist.
        """
        raise NotImplementedError(f"{self.name} does not support patching secrets.")

    @abstractmethod
    async def encrypt(self, context: str, plaintext: str) -> str:
        """Encrypt ``plaintext`` bound to ``context`` (for example the organization id)."""

    async def encrypt_many(self, items: Sequence[tuple[str, str]]) -> list[str]:
        """Encrypt many ``(context, plaintext)`` pairs in one call; added in 1.1.

        Each item may bind a different context (for example a different asset custom field key),
        so a ciphertext encrypted for one field or one organization can never be replayed into
        another (§B8.1). Default implementation loops over :meth:`encrypt`; a provider with a
        native batch endpoint (OpenBao transit) overrides this for one round trip. Order of the
        result matches the order of ``items``; any failure leaves nothing encrypted for the whole
        call (callers must not act on a partial result).
        """
        return [await self.encrypt(context, plaintext) for context, plaintext in items]

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
