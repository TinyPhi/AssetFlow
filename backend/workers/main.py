# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The worker process: `python -m workers.main` (§B9.3, §B4.1).

Connects as the worker database role, wakes on a PostgreSQL NOTIFY or every
`workers.outbox.poll_interval_seconds` (the poll is the backup when a notification is lost), and
stops cleanly on SIGTERM or SIGINT: the row in progress finishes, unstarted claimed rows are
released. `python -m workers.main --healthcheck` exits 0 when the heartbeat file is fresh.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import socket
import sys
import time
from pathlib import Path

from app.core.config import AppConfig, ConfigError, load_config
from app.core.db import DirectConnection, close_pool, connect_direct, init_pool
from app.providers.registry import ProviderRegistry
from workers.outbox_dispatcher import DispatcherOptions, run_once
from workers.subscribers import SubscriberRegistry, default_registry

logger = logging.getLogger(__name__)

HEARTBEAT_MAX_AGE_SECONDS = 30.0
DEFAULT_NOTIFY_CHANNEL = "outbox_events"


def worker_id() -> str:
    """Host name and process id; recorded in `outbox.claimed_by` (no personal data)."""
    return f"{socket.gethostname()}-{os.getpid()}"


def _touch(path: Path) -> None:
    try:
        path.touch()
    except OSError:
        logger.warning("worker.heartbeat_failed")


def heartbeat_is_fresh(path: Path, max_age_seconds: float = HEARTBEAT_MAX_AGE_SECONDS) -> bool:
    """True when the heartbeat file exists and was touched recently."""
    try:
        return time.time() - path.stat().st_mtime <= max_age_seconds
    except OSError:
        return False


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows event loops have no add_signal_handler
            signal.signal(sig, lambda _s, _f: loop.call_soon_threadsafe(stop.set))


async def _listen(cfg: AppConfig, registry: ProviderRegistry, wake: asyncio.Event) -> DirectConnection | None:
    """Open the LISTEN connection; None (poll only) when it cannot be opened."""
    outbox = cfg.workers.outbox
    channel = str(cfg.providers.events.settings.get("notify_channel", DEFAULT_NOTIFY_CHANNEL))
    try:
        conn = await connect_direct(
            cfg.database, "worker", registry.resolve_secret, host=outbox.listen_host, port=outbox.listen_port
        )
        await conn.add_listener(channel, lambda *_args: wake.set())
    except (OSError, ValueError) as exc:
        logger.warning("worker.listen_unavailable", extra={"error_code": type(exc).__name__})
        return None
    return conn


async def serve(
    cfg: AppConfig, providers: ProviderRegistry, subscribers: SubscriberRegistry, stop: asyncio.Event
) -> None:
    """Run the dispatch loop until `stop` is set."""
    outbox = cfg.workers.outbox
    options = DispatcherOptions(outbox.batch_size, outbox.reclaim_after_seconds, outbox.max_attempts)
    heartbeat = Path(cfg.workers.heartbeat_file)
    me = worker_id()
    pool = await init_pool(cfg.database, "worker", providers.resolve_secret)
    wake = asyncio.Event()
    listener = await _listen(cfg, providers, wake)
    try:
        while not stop.is_set():
            _touch(heartbeat)
            handled = await run_once(
                pool, subscribers, me, options, telemetry=providers.telemetry, should_stop=stop.is_set
            )
            if handled >= outbox.batch_size:
                continue  # a full batch: more is probably waiting
            wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(wake.wait(), timeout=outbox.poll_interval_seconds)
            if stop.is_set():
                break
    finally:
        if listener is not None:
            await listener.close()
        await close_pool(pool)


async def run(config_path: str | None) -> int:
    """Load config, build providers, serve until SIGTERM."""
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    providers = ProviderRegistry.from_config(cfg)
    stop = asyncio.Event()
    _install_signal_handlers(stop)
    try:
        await serve(cfg, providers, default_registry(), stop)
    finally:
        await providers.aclose()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", help="path to assetflow.yaml (else ASSETFLOW_CONFIG or the default)")
    parser.add_argument("--healthcheck", action="store_true", help="exit 0 when the heartbeat is fresh")
    args = parser.parse_args(argv)
    if args.healthcheck:
        try:
            cfg = load_config(args.config)
        except ConfigError:
            return 1
        return 0 if heartbeat_is_fresh(Path(cfg.workers.heartbeat_file)) else 1
    logging.basicConfig(level=logging.INFO)
    return asyncio.run(run(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
