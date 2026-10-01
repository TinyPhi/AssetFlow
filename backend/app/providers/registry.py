# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Provider registry (§B6.1, §B6.2, M1.3-T7).

Config alone picks each provider: ``providers.<pillar>.type`` is looked up first among the
built-in factories and then among the ``assetflow.providers.<pillar>`` entry points of installed
packages (§B6.1 rule 7). An unknown type, a factory error or a provider of the wrong interface
raises ``ConfigError`` naming the exact config path. A pillar missing from the file uses its
fallback and the config loader logs a warning (§B6.1 rule 5).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from importlib.metadata import EntryPoint, entry_points
from typing import Any

from app.core.config import FALLBACK_PROVIDERS, PILLARS, AppConfig, ConfigError, Pillar, is_secret_ref
from app.core.problems import SecretsUnavailableError
from app.providers.auth.base import AuthProvider
from app.providers.auth.mock import MockAuthProvider
from app.providers.auth.oidc import OidcAuthProvider
from app.providers.context import ProviderContext
from app.providers.events.base import EventBusProvider
from app.providers.events.inmemory import InMemoryEventBusProvider
from app.providers.events.postgres import PostgresEventBusProvider
from app.providers.secrets.base import SecretsProvider
from app.providers.secrets.file import FileSecretsProvider
from app.providers.secrets.openbao import OpenBaoSecretsProvider
from app.providers.telemetry.base import TelemetryProvider
from app.providers.telemetry.noop import NoOpTelemetryProvider
from app.providers.telemetry.otel import OtelTelemetryProvider

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[dict[str, Any], ProviderContext], object]

ENTRY_POINT_GROUP = "assetflow.providers.{pillar}"


#: Built-in providers per pillar.
BUILTIN_FACTORIES: dict[Pillar, dict[str, ProviderFactory]] = {
    "auth": {
        "mock": MockAuthProvider.from_settings,
        "oidc": OidcAuthProvider.from_settings,
    },
    "secrets": {
        "file": FileSecretsProvider.from_settings,
        "openbao": OpenBaoSecretsProvider.from_settings,
    },
    "telemetry": {
        "noop": NoOpTelemetryProvider.from_settings,
        "otel": OtelTelemetryProvider.from_settings,
    },
    "events": {
        "inmemory": InMemoryEventBusProvider.from_settings,
        "postgres": PostgresEventBusProvider.from_settings,
    },
}


INTERFACES: dict[Pillar, type[object]] = {
    "auth": AuthProvider,
    "secrets": SecretsProvider,
    "telemetry": TelemetryProvider,
    "events": EventBusProvider,
}


def _entry_points(pillar: Pillar) -> dict[str, EntryPoint]:
    found: dict[str, EntryPoint] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP.format(pillar=pillar)):
        if ep.name in BUILTIN_FACTORIES[pillar]:
            logger.warning("ignoring entry point %s for providers.%s: the name is built in", ep.value, pillar)
            continue
        found[ep.name] = ep
    return found


def _factory(pillar: Pillar, type_name: str) -> ProviderFactory:
    builtin = BUILTIN_FACTORIES[pillar].get(type_name)
    if builtin is not None:
        return builtin
    external = _entry_points(pillar)
    ep = external.get(type_name)
    if ep is None:
        known = sorted({*BUILTIN_FACTORIES[pillar], *external})
        raise ConfigError(
            [(f"providers.{pillar}.type", f"unknown provider {type_name!r}; available: {', '.join(known)}")]
        )
    try:
        loaded = ep.load()
    except (ImportError, AttributeError) as exc:
        raise ConfigError(
            [(f"providers.{pillar}.type", f"provider {type_name!r} ({ep.value}) cannot be loaded: {exc}")]
        ) from exc
    factory: ProviderFactory = getattr(loaded, "from_settings", loaded)
    if not callable(factory):
        raise ConfigError([(f"providers.{pillar}.type", f"provider {type_name!r} is not callable")])
    return factory


def build_provider(cfg: AppConfig, pillar: Pillar) -> object:
    """Build one pillar's provider from ``providers.<pillar>`` and check its interface."""
    pcfg = cfg.providers.for_pillar(pillar)
    context = ProviderContext(env=cfg.env, pillar=pillar, base_dir=cfg.base_dir)
    provider = _factory(pillar, pcfg.type)(dict(pcfg.settings), context)
    interface = INTERFACES[pillar]
    path = f"providers.{pillar}.type"
    if not isinstance(provider, interface):
        raise ConfigError([(path, f"provider {pcfg.type!r} does not implement {interface.__name__}")])
    if getattr(provider, "INTERFACE_VERSION", None) != getattr(interface, "INTERFACE_VERSION", None):
        raise ConfigError([(path, f"provider {pcfg.type!r} has an unsupported INTERFACE_VERSION")])
    return provider


class ProviderRegistry:
    """The active provider of each pillar."""

    def __init__(
        self,
        auth: AuthProvider,
        secrets: SecretsProvider,
        telemetry: TelemetryProvider,
        events: EventBusProvider,
        *,
        env: str = "development",
        types: dict[str, str] | None = None,
    ) -> None:
        self.auth = auth
        self.secrets = secrets
        self.telemetry = telemetry
        self.events = events
        self.env = env
        self.types: dict[str, str] = types or {}

    @classmethod
    def from_config(cls, cfg: AppConfig) -> ProviderRegistry:
        """Build every pillar from ``cfg.providers``; raises ``ConfigError`` with the exact path."""
        auth = build_provider(cfg, "auth")
        secrets = build_provider(cfg, "secrets")
        telemetry = build_provider(cfg, "telemetry")
        events = build_provider(cfg, "events")
        # build_provider already verified each interface; these checks narrow the static types.
        if not isinstance(auth, AuthProvider) or not isinstance(secrets, SecretsProvider):
            raise TypeError("provider interface mismatch")
        if not isinstance(telemetry, TelemetryProvider) or not isinstance(events, EventBusProvider):
            raise TypeError("provider interface mismatch")
        return cls(
            auth,
            secrets,
            telemetry,
            events,
            env=cfg.env,
            types={p: cfg.providers.for_pillar(p).type for p in PILLARS},
        )

    async def resolve_secret(self, ref: str) -> str:
        """Resolve a config secret value for the database pool and similar consumers.

        ``secret://`` references go to the active secrets provider (a missing secret raises
        ``SecretsUnavailableError``, never a default). Outside production, any other value was
        already expanded from a ``${VAR}`` interpolation by the config loader and is returned as is.
        """
        if is_secret_ref(ref):
            return await self.secrets.get(ref)
        if ref.startswith("secret://"):
            raise SecretsUnavailableError("A secret reference is malformed.")
        if self.env == "production" or not ref:
            raise SecretsUnavailableError("A required secret is not a secret:// reference.")
        return ref

    async def health(self) -> dict[str, Any]:
        """Aggregate ``health()`` of every pillar (§B6.1 rule 4). Exception text is never exposed."""
        providers = (self.auth, self.secrets, self.telemetry, self.events)
        results = await asyncio.gather(*(p.health() for p in providers), return_exceptions=True)
        report: dict[str, dict[str, Any]] = {}
        names = [p.name for p in providers]
        for pillar, name, result in zip(PILLARS, names, results, strict=True):
            if isinstance(result, BaseException):
                logger.error("health check of providers.%s failed", pillar, exc_info=result)
                report[pillar] = {"status": "unhealthy", "provider": self.types.get(pillar, name)}
            elif isinstance(result, dict) and result.get("status") in {"healthy", "degraded", "unhealthy"}:
                report[pillar] = result
            else:
                report[pillar] = {"status": "unhealthy", "provider": self.types.get(pillar, name)}
        statuses = {entry["status"] for entry in report.values()}
        overall = "healthy"
        for level in ("degraded", "unhealthy"):
            if level in statuses:
                overall = level
        return {"status": overall, "providers": report}

    async def aclose(self) -> None:
        """Close every provider that has an ``aclose()`` (or ``close()``) method, in reverse order.

        A failure is logged and does not stop the other providers from closing.
        """
        for pillar, provider in reversed(
            list(zip(PILLARS, (self.auth, self.secrets, self.telemetry, self.events), strict=True))
        ):
            closer = getattr(provider, "aclose", None) or getattr(provider, "close", None)
            if closer is None:
                continue
            try:
                result = closer()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("closing providers.%s failed", pillar)


def init_providers(cfg: AppConfig) -> ProviderRegistry:
    """Deprecated alias of :meth:`ProviderRegistry.from_config`."""
    return ProviderRegistry.from_config(cfg)


__all__ = [
    "BUILTIN_FACTORIES",
    "ENTRY_POINT_GROUP",
    "FALLBACK_PROVIDERS",
    "ProviderFactory",
    "ProviderRegistry",
    "build_provider",
    "init_providers",
]
