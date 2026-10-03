# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Reuses the isolation suite's real-PostgreSQL harness (§C8.3, §C8.5) for sign-in e2e tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "isolation"))

from pg_harness import isolation_db, make_pool, pg_server

__all__ = ["isolation_db", "make_pool", "pg_server"]
