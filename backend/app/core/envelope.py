# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""AssetFlow success envelope (§C1.5).

Success responses are ``{"status": "success", "status_code", "message", "timestamp", "request_id",
"data"}``. Errors never use this envelope; they are RFC 9457 problems (app.core.problems).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Literal

from pydantic import BaseModel, Field


def now_utc_iso() -> str:
    """Return the current UTC time as ISO 8601 with a ``Z`` suffix."""
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class ApiEnvelope[T](BaseModel):
    """Top-level success response envelope."""

    status: Literal["success"] = Field(default="success", description="Always 'success'")
    status_code: int = Field(default=200, description="HTTP status code")
    message: str = Field(default="OK", description="Human-readable summary")
    timestamp: str = Field(default_factory=now_utc_iso, description="ISO 8601 UTC time of the response")
    request_id: str = Field(default="", description="Correlates with logs and traces")
    data: T = Field(description="Response payload")


def success_response(
    data: Any,
    *,
    message: str = "OK",
    status_code: int = 200,
    request_id: str = "",
) -> dict[str, Any]:
    """Build a success envelope as a plain dict."""
    return {
        "status": "success",
        "status_code": status_code,
        "message": message,
        "timestamp": now_utc_iso(),
        "request_id": request_id,
        "data": data,
    }
