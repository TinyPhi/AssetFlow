# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""AuthProvider interface (§B6.1, §B6.2), INTERFACE_VERSION 1.0.

Implementations (``oidc`` with the Zitadel preset, ``mock`` for dev/test, or a third-party entry
point) pass the shared suite in ``tests/contract/auth/``. ``verify_token`` raises
``app.core.problems.UnauthorizedError`` for any token it does not accept; it never falls back to
a default principal.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Principal:
    """Authenticated user or machine client (§B6.2)."""

    subject: str
    organization_id: str
    roles: list[str] = field(default_factory=list)
    email: str | None = None
    name: str | None = None
    is_machine: bool = False
    client_id: str | None = None


class AuthProvider(ABC):
    """Authentication and identity provider."""

    INTERFACE_VERSION: str = "1.0"

    @property
    def name(self) -> str:
        """Provider implementation identifier."""
        return self.__class__.__name__

    @abstractmethod
    async def verify_token(self, token: str) -> Principal:
        """Verify a bearer token and return its principal; raise UnauthorizedError otherwise."""

    @abstractmethod
    async def discovery(self) -> dict[str, Any]:
        """Return the OIDC discovery document."""

    @abstractmethod
    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> dict[str, Any]:
        """Exchange an authorization code for tokens."""

    @abstractmethod
    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        """Exchange a refresh token for new tokens; raise UnauthorizedError when it is not valid."""

    @abstractmethod
    async def revoke(self, token: str) -> None:
        """Revoke a token."""

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        """Return ``{"status": "healthy" | "degraded" | "unhealthy", ...}`` without secrets or paths."""
