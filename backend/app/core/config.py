# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""AssetFlow platform configuration loader and validator (§B7.2, §B7.4, §B6.1 rule 6, decision 51).

``load_config`` reads ``config/assetflow.yaml`` (or the file named by the argument or by
``ASSETFLOW_CONFIG``), expands ``${VAR}`` / ``${VAR:-default}`` environment interpolations and
validates the result with Pydantic. Any problem raises :class:`ConfigError` carrying the exact
path of every offending value, formatted like ``providers.auth.settings.items[1][2]``.

The file never contains secret values: database passwords are ``secret://<area>/<name>#<key>``
references (§C1.6), resolved at runtime through the secrets provider. In development and test a
password may instead be a bare environment interpolation (``${ASSETFLOW_DB_API_PASSWORD}``).

CLI: ``python -m app.core.config validate <file>`` (exit 0 when valid, 1 otherwise).
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    ValidationInfo,
    model_validator,
)

logger = logging.getLogger(__name__)

Environment = Literal["development", "test", "staging", "production"]
Pillar = Literal["auth", "secrets", "telemetry", "events"]

PILLARS: tuple[Pillar, ...] = ("auth", "secrets", "telemetry", "events")
DB_ROLES: tuple[str, ...] = ("api", "worker", "migrator")

#: Fallback provider per pillar when ``providers.<pillar>`` is absent (§B6.1 rule 5, §B6.2).
FALLBACK_PROVIDERS: dict[Pillar, str] = {
    "auth": "mock",
    "secrets": "file",
    "telemetry": "noop",
    "events": "inmemory",
}

#: ``secret://<area>/<name>#<key>`` (§C1.6). ``<name>`` may contain further path segments.
SECRET_REF_PATTERN = re.compile(
    r"^secret://(?P<area>[A-Za-z0-9_-]+)/(?P<name>[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)#(?P<key>[A-Za-z0-9_.-]+)$"
)
_ENV_PATTERN = re.compile(r"\$\{(?P<var>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}")
_BARE_ENV_PATTERN = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = _REPO_ROOT / "config" / "assetflow.yaml"
CONFIG_ENV_VAR = "ASSETFLOW_CONFIG"

PathPart = str | int


class ConfigError(Exception):
    """Invalid platform configuration. Boot stops; every entry names the exact config path."""

    def __init__(self, errors: Sequence[tuple[str, str]], *, source: str | None = None) -> None:
        self.errors: list[tuple[str, str]] = list(errors)
        self.source = source
        head = f"invalid configuration in {source}" if source else "invalid configuration"
        lines = "\n".join(f"  {path}: {message}" if path else f"  {message}" for path, message in self.errors)
        super().__init__(f"{head}:\n{lines}")


def format_path(parts: Iterable[PathPart]) -> str:
    """Format a location as ``a.b[1][2]`` (§B7.4)."""
    out = ""
    for part in parts:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out = f"{out}.{part}" if out else part
    return out


def is_secret_ref(value: str) -> bool:
    """True when ``value`` is a well-formed ``secret://<area>/<name>#<key>`` reference."""
    if SECRET_REF_PATTERN.match(value) is None:
        return False
    segments = re.split(r"[/#]", value[len("secret://") :])
    return not any(segment in {".", ".."} for segment in segments)


def parse_secret_ref(ref: str) -> tuple[str, str, str]:
    """Parse ``secret://<area>/<name>#<key>`` into ``(area, name, key)``."""
    match = SECRET_REF_PATTERN.match(ref)
    if match is None or not is_secret_ref(ref):
        raise ValueError(f"Invalid secret reference: {ref!r}")
    return match.group("area"), match.group("name"), match.group("key")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlatformConfig(_Strict):
    """Installation-wide settings (§B7.2 ``platform``, §B5.7)."""

    admins: list[str] = Field(default_factory=list, description="Platform admins (IdP subjects)")
    allow_open_provisioning: bool = Field(default=False, description="Permit the `open` policy in production")
    public_url: str | None = Field(default=None, description="Public base URL of the web app")
    allowed_origins: list[str] = Field(default_factory=list, description="Allowed browser origins (CORS)")


class ProviderConfig(_Strict):
    """One provider pillar: ``providers.<pillar>.type`` chooses the implementation (§B6.1 rule 3)."""

    type: str = Field(min_length=1, description="Provider type (built-in name or entry-point name)")
    settings: dict[str, Any] = Field(default_factory=dict, description="Provider-specific settings")
    _is_fallback: bool = PrivateAttr(default=False)

    @property
    def is_fallback(self) -> bool:
        """True when the pillar was absent from the file and the fallback was chosen (§B6.1 rule 5)."""
        return self._is_fallback


def _fallback(pillar: Pillar) -> ProviderConfig:
    cfg = ProviderConfig(type=FALLBACK_PROVIDERS[pillar])
    cfg._is_fallback = True
    return cfg


class ProvidersConfig(_Strict):
    """``providers.*`` (§B7.2). A missing pillar falls back to its dev/test implementation."""

    auth: ProviderConfig = Field(default_factory=lambda: _fallback("auth"))
    secrets: ProviderConfig = Field(default_factory=lambda: _fallback("secrets"))
    telemetry: ProviderConfig = Field(default_factory=lambda: _fallback("telemetry"))
    events: ProviderConfig = Field(default_factory=lambda: _fallback("events"))

    def for_pillar(self, pillar: Pillar) -> ProviderConfig:
        """Return the provider config of one pillar."""
        cfg: ProviderConfig = getattr(self, pillar)
        return cfg


class DbRoleConfig(_Strict):
    """Credentials of one database role. ``password`` is a secret reference, never a value."""

    user: str = Field(min_length=1)
    password: str = Field(min_length=1, description="secret://<area>/<name>#<key> (or ${VAR} in dev/test)")


class DatabaseConfig(_Strict):
    """PostgreSQL connection settings (§B7.2 ``database``, M1.3-T2)."""

    host: str = Field(min_length=1)
    port: int = Field(default=5432, ge=1, le=65535)
    name: str = Field(min_length=1)
    api: DbRoleConfig
    worker: DbRoleConfig
    migrator: DbRoleConfig
    behind_pgbouncer: bool = False
    statement_timeout_ms: int = Field(default=15000, ge=1)
    idle_in_transaction_timeout_ms: int = Field(default=30000, ge=1)
    pool_min: int = Field(default=1, ge=0)
    pool_max: int = Field(default=10, ge=1)

    @model_validator(mode="after")
    def _pool_bounds(self) -> DatabaseConfig:
        if self.pool_min > self.pool_max:
            raise ValueError("pool_min must not exceed pool_max")
        return self


class OutboxWorkerConfig(_Strict):
    """``workers.outbox``: the outbox dispatcher (§B9.3, M1.5-T1)."""

    batch_size: int = Field(default=50, ge=1, le=1000, description="Outbox rows claimed per batch")
    poll_interval_seconds: float = Field(
        default=2.0, gt=0, description="Seconds between polls when no NOTIFY wakes the dispatcher"
    )
    reclaim_after_seconds: int = Field(
        default=300, ge=1, description="A claim older than this many seconds is returned to the queue"
    )
    max_attempts: int = Field(
        default=5, ge=1, description="Claims after which a failing event is dead-lettered"
    )
    listen_host: str | None = Field(
        default=None,
        description="Direct PostgreSQL host for LISTEN (not PgBouncer); defaults to database.host",
    )
    listen_port: int | None = Field(
        default=None,
        ge=1,
        le=65535,
        description="Direct PostgreSQL port for LISTEN; defaults to database.port",
    )


class WorkersConfig(_Strict):
    """``workers.*``: settings of the separate worker process (§B9.3)."""

    outbox: OutboxWorkerConfig = Field(default_factory=OutboxWorkerConfig)
    heartbeat_file: str = Field(
        default="/tmp/af-worker-heartbeat",  # noqa: S108 - a tmpfs path inside the container
        min_length=1,
        description="File the worker touches every loop; the container healthcheck reads its age",
    )


class AppConfig(_Strict):
    """Root of ``config/assetflow.yaml``."""

    env: Environment = "development"
    platform: PlatformConfig = Field(default_factory=PlatformConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    database: DatabaseConfig
    workers: WorkersConfig = Field(default_factory=WorkersConfig)
    _source: Path | None = PrivateAttr(default=None)

    @property
    def source(self) -> Path | None:
        """The file this config was loaded from (None when built in code)."""
        return self._source

    @property
    def base_dir(self) -> Path:
        """Directory that relative paths in provider settings resolve against."""
        return self._source.parent if self._source else Path.cwd()

    @model_validator(mode="after")
    def _guards(self, info: ValidationInfo) -> AppConfig:
        context: Mapping[str, Any] = info.context or {}
        env_interpolated: set[str] = set(context.get("env_interpolated", ()))
        organizations: Mapping[str, str] = context.get("organization_provisioning", {})
        errors: list[tuple[str, str]] = []

        for role in DB_ROLES:
            path = f"database.{role}.password"
            value = getattr(self.database, role).password
            if is_secret_ref(value):
                continue
            if self.env == "production":
                errors.append((path, "must be a secret://<area>/<name>#<key> reference in production"))
            elif path not in env_interpolated:
                errors.append((path, "must be a secret:// reference or a ${VAR} interpolation"))

        if self.env == "production":
            if self.providers.auth.type == "mock":
                errors.append(("providers.auth.type", "mock auth is refused in production"))
            if self.providers.secrets.type == "file":
                errors.append(("providers.secrets.type", "file secrets are refused in production"))
            if self.providers.telemetry.settings.get("scrub") is False:
                errors.append(("providers.telemetry.settings.scrub", "cannot be disabled in production"))
            for source, policy in sorted(organizations.items()):
                if policy == "open" and not self.platform.allow_open_provisioning:
                    errors.append(
                        (
                            f"{source}.provisioning",
                            "open provisioning needs platform.allow_open_provisioning: true in production",
                        )
                    )

        if errors:
            raise ConfigError(errors)
        return self


# --------------------------------------------------------------------------------------------- loading


def _interpolate(value: Any, path: list[PathPart], errors: list[tuple[str, str]], hits: set[str]) -> Any:
    """Expand ``${VAR}`` / ``${VAR:-default}``; an unset variable without a default is an error."""
    if isinstance(value, str):
        if _BARE_ENV_PATTERN.match(value):
            hits.add(format_path(path))

        def _replace(match: re.Match[str]) -> str:
            var, default = match.group("var"), match.group("default")
            env_value = os.environ.get(var)
            if env_value is not None:
                return env_value
            if default is not None:
                return default
            errors.append((format_path(path), f"environment variable {var} is not set"))
            return ""

        return _ENV_PATTERN.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _interpolate(v, [*path, str(k)], errors, hits) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v, [*path, i], errors, hits) for i, v in enumerate(value)]
    return value


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark is not None else ""
        raise ConfigError([("", f"YAML syntax error{where}")], source=str(path)) from exc
    except OSError as exc:
        raise ConfigError([("", f"cannot read file: {exc.strerror}")], source=str(path)) from exc


def _organization_provisioning(config_dir: Path) -> dict[str, str]:
    """Read ``provisioning`` from ``<config dir>/organizations/*.yaml`` (§B5.6) for the boot guard."""
    policies: dict[str, str] = {}
    org_dir = config_dir / "organizations"
    if not org_dir.is_dir():
        return policies
    for org_file in sorted(org_dir.glob("*.y*ml")):
        data = _read_yaml(org_file)
        if isinstance(data, dict) and isinstance(data.get("provisioning"), str):
            policies[f"organizations/{org_file.name}"] = data["provisioning"]
    return policies


def resolve_config_path(path: str | Path | None = None) -> Path:
    """Argument, else ``ASSETFLOW_CONFIG``, else ``<repo>/config/assetflow.yaml``."""
    if path is not None:
        return Path(path)
    env_path = os.environ.get(CONFIG_ENV_VAR)
    return Path(env_path) if env_path else DEFAULT_CONFIG_PATH


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load and validate the platform config. Raises :class:`ConfigError` on any problem."""
    target = resolve_config_path(path)
    source = str(target)
    if not target.is_file():
        raise ConfigError([("", "config file not found")], source=source)

    raw = _read_yaml(target)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError([("", "top level must be a mapping")], source=source)

    errors: list[tuple[str, str]] = []
    env_interpolated: set[str] = set()
    data = _interpolate(raw, [], errors, env_interpolated)
    if errors:
        raise ConfigError(errors, source=source)

    organizations = _organization_provisioning(target.parent)
    context: dict[str, Any] = {
        "env_interpolated": env_interpolated,
        "organization_provisioning": organizations,
    }
    try:
        cfg = AppConfig.model_validate(data, context=context)
    except ValidationError as exc:
        details = [(format_path(err["loc"]), err["msg"]) for err in exc.errors()]
        raise ConfigError(details, source=source) from exc
    except ConfigError as exc:
        raise ConfigError(exc.errors, source=source) from exc

    cfg._source = target.resolve()
    _warn(cfg, organizations)
    return cfg


def _warn(cfg: AppConfig, organizations: Mapping[str, str]) -> None:
    for pillar in PILLARS:
        pcfg = cfg.providers.for_pillar(pillar)
        if pcfg.is_fallback:
            logger.warning(
                "providers.%s is not configured; using the %r fallback (§B6.1 rule 5)", pillar, pcfg.type
            )
    if cfg.env == "production":
        if not cfg.platform.admins:
            logger.warning("platform.admins is empty; no one can administer this installation (§B5.7)")
        if cfg.platform.allow_open_provisioning and "open" in organizations.values():
            logger.warning("open provisioning is enabled in production (platform.allow_open_provisioning)")


# ------------------------------------------------------------------------------------------------- CLI

_USAGE = "usage: python -m app.core.config validate <file>\n"


#: Channels built into AssetFlow (§B6.3); a third-party channel package extends this at runtime,
#: out of scope for this static check.
_BUILTIN_CHANNELS = frozenset({"inapp", "email", "webhook"})


def _validate_domain_templates(platform_config_file: str) -> list[str]:
    """Validate every `config/domains/*.yaml` next to `platform_config_file` (§B7.3, §B7.4).

    Returns one problem string per cross-reference failure, each naming its exact path; empty when
    there is nothing to check yet (`config/domains/` has no real templates until master Phase 2).
    """
    # Local: keeps core/config's own import-time surface free of the organization feature module
    # for every ordinary boot; only the CLI validate path (this function) needs it.
    from app.core.domain_template import (  # noqa: PLC0415
        DomainTemplateError,
        load_domain_template,
        validate_automations,
    )
    from app.engines.automation.registry import default_registry  # noqa: PLC0415

    base = Path(platform_config_file).resolve().parent
    domains_dir = base / "domains"
    templates_dir = base / "templates" / "en"
    if not domains_dir.is_dir():
        return []
    registry = default_registry()
    problems: list[str] = []
    for template_file in sorted(domains_dir.glob("*.yaml")):
        try:
            template = load_domain_template(template_file)
        except DomainTemplateError as exc:
            problems.append(f"{template_file.name}: {exc.path}: {exc.message}")
            continue
        for problem in validate_automations(
            template, known_channels=set(_BUILTIN_CHANNELS), registry=registry, templates_dir=templates_dir
        ):
            problems.append(f"{template_file.name}: {problem}")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """``validate <file>``: exit 0 when the file is valid, 1 otherwise (§B7.4)."""
    args: list[str] = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != "validate":
        sys.stderr.write(_USAGE)
        return 1
    try:
        cfg = load_config(args[1])
    except ConfigError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    domain_problems = _validate_domain_templates(args[1])
    if domain_problems:
        for problem in domain_problems:
            sys.stderr.write(f"{problem}\n")
        return 1
    sys.stdout.write(f"config valid: {args[1]} (env={cfg.env})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
