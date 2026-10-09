# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""OpenAPI route metadata helpers shared by every layer (permission and visibility markers)."""

from __future__ import annotations

from typing import Any


def permission_extra(permission: str) -> dict[str, Any]:
    """Declare required permission metadata on an OpenAPI route."""
    return {"x-assetflow-permission": permission}


def public_extra() -> dict[str, Any]:
    """Declare public visibility metadata on an OpenAPI route."""
    return {"x-assetflow-public": True}
