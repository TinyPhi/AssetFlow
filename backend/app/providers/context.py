# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""What the registry passes to every provider factory (§B6.1 rules 3 and 7).

A provider factory, built-in or registered through the ``assetflow.providers.<pillar>`` entry
point group, is called as ``factory(settings, context)`` where ``settings`` is
``providers.<pillar>.settings`` from the config file. A class may instead expose a
``from_settings(settings, context)`` classmethod, which the registry prefers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.config import ConfigError, Environment, Pillar, format_path, is_guarded_env


@dataclass(frozen=True)
class ProviderContext:
    """Installation facts a provider may need; never request objects (§B6.1 rule 8)."""

    env: Environment
    pillar: Pillar
    base_dir: Path

    @property
    def is_production(self) -> bool:
        """True in ``env: production``."""
        return self.env == "production"

    @property
    def is_guarded(self) -> bool:
        """True in every environment except ``development`` and ``test`` (AF-004)."""
        return is_guarded_env(self.env)

    def settings_path(self) -> str:
        """Config path of this pillar's settings, for error messages."""
        return f"providers.{self.pillar}.settings"


class ProviderSettings(BaseModel):
    """Base for a provider's typed settings: unknown keys are errors."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def parse_settings[S: ProviderSettings](
    model: type[S], settings: dict[str, Any], context: ProviderContext
) -> S:
    """Validate ``settings`` against ``model``; errors carry the exact config path."""
    try:
        return model.model_validate(settings)
    except ValidationError as exc:
        base = context.settings_path()
        errors = [(f"{base}.{format_path(e['loc'])}" if e["loc"] else base, e["msg"]) for e in exc.errors()]
        raise ConfigError(errors) from exc


def refuse_in_production(context: ProviderContext, what: Literal["mock auth", "file secrets"]) -> None:
    """Second line of defence behind the config guard (§B6.1 rule 6)."""
    if context.is_guarded:
        raise ConfigError([(f"providers.{context.pillar}.type", f"{what} is refused in {context.env}")])
