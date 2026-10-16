# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""A channel's per-organization settings as JSON Schema, for the admin form (§B6.3 D17, M1.5-T8).

The schema is the channel's own Pydantic model, so the form, the browser validator and the server's
validation can never disagree. Secret fields are marked write-only (`writeOnly`, `format: password`
and the AssetFlow extension `x-assetflow-secret`) and never carry a default or an example. Field
`title` and `description` come from the model; the frontend turns them into translation keys
(`notification_channels.<key>.<field>.label`), so no translated text is in the schema.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.channels.base import NotificationChannel

__all__ = ["export_schema", "schema_etag"]

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def export_schema(channel: type[NotificationChannel]) -> dict[str, Any]:
    """The settings schema of `channel`, with its secret fields marked write-only."""
    schema = channel.config_schema.model_json_schema(mode="validation")
    schema.pop("description", None)  # the model's docstring: developer notes, not form text
    properties: dict[str, Any] = schema.setdefault("properties", {})
    for name in channel.secret_fields:
        prop = properties.setdefault(name, {"type": "string"})
        prop.pop("default", None)
        prop.pop("examples", None)
        prop["writeOnly"] = True
        prop["format"] = "password"
        prop["x-assetflow-secret"] = True
    schema["$schema"] = JSON_SCHEMA_DIALECT
    schema["$id"] = f"/api/v1/notification-channels/{channel.key}/schema"
    schema["x-assetflow-channel"] = channel.key
    return schema


def schema_etag(schema: dict[str, Any]) -> str:
    """A strong validator for the schema: a hash of its canonical form (§B4.5)."""
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return '"' + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32] + '"'
