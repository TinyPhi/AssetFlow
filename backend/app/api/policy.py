# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Environment policy of the HTTP layer, applied at boot (AF-023, AF-033, NEW-1, NEW-3).

Pure functions over the loaded config. The config is read through :func:`setting` so the same code
serves the real ``AppConfig`` and the plain mappings some tests use. An unknown environment is
treated as ``production`` (fail closed): only ``development`` and ``test`` relax a guard.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final

from app.core.config import ConfigError, is_secret_ref
from app.core.cookie_crypto import derive_key

RELAXED_ENVIRONMENTS: Final = frozenset({"development", "test"})
MIN_COOKIE_KEY_LENGTH: Final = 32
COOKIE_KEY_SETTING: Final = "session_cookie_key"

SecretResolver = Callable[[str], Awaitable[str]]


def setting(config: Any, *path: str, default: Any = None) -> Any:
    """Read ``config.a.b`` or ``config["a"]["b"]``; ``default`` when any step is missing."""
    node = config
    for part in path:
        node = node.get(part, default) if isinstance(node, Mapping) else getattr(node, part, default)
        if node is default:
            return default
    return node


def environment(config: Any) -> str:
    """The configured environment; anything unknown counts as production."""
    env = setting(config, "env")
    return env if isinstance(env, str) and env else "production"


def is_relaxed(config: Any) -> bool:
    """True only for ``development`` and ``test``."""
    return environment(config) in RELAXED_ENVIRONMENTS


def docs_enabled(config: Any) -> bool:
    """``/docs``, ``/redoc`` and ``/openapi.json`` exist only in development and test (AF-033)."""
    return is_relaxed(config)


def mock_auth_enabled(config: Any) -> bool:
    """The mock sign-in routes exist only for the mock provider in development or test (NEW-3)."""
    return is_relaxed(config) and setting(config, "providers", "auth", "type") == "mock"


def allowed_origins(config: Any) -> list[str]:
    """CORS origins from ``platform.allowed_origins``; ``*`` is refused outside development/test."""
    raw = setting(config, "platform", "allowed_origins", default=[])
    origins = [str(o).strip() for o in raw or [] if str(o).strip()]
    if "*" in origins and not is_relaxed(config):
        raise ConfigError([("platform.allowed_origins", "'*' is refused outside development and test")])
    return origins


async def session_cookie_key(config: Any, resolve_secret: SecretResolver) -> bytes:
    """Resolve the 32-byte AES-GCM refresh-cookie key from ``session_cookie_key`` (a ``secret://`` reference).

    Required outside development/test (boot refuses without it). In development/test a missing
    reference yields a random per-process key, so refresh cookies do not survive a restart; no key
    is ever hard-coded.
    """
    ref = setting(config, COOKIE_KEY_SETTING)
    if not ref:
        if is_relaxed(config):
            return derive_key(secrets.token_bytes(MIN_COOKIE_KEY_LENGTH))
        raise ConfigError([(COOKIE_KEY_SETTING, "is required outside development and test")])
    if not isinstance(ref, str) or not is_secret_ref(ref):
        raise ConfigError([(COOKIE_KEY_SETTING, "must be a secret://<area>/<name>#<key> reference")])
    value = await resolve_secret(ref)
    if len(value) < MIN_COOKIE_KEY_LENGTH:
        raise ConfigError(
            [(COOKIE_KEY_SETTING, f"the secret must be at least {MIN_COOKIE_KEY_LENGTH} characters")]
        )
    return derive_key(value)
