# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Resource factories and minimal fixture map for authorization matrix tests (§B11.6, §C8.4)."""

from __future__ import annotations

from typing import Any

DEFAULT_UUID = "00000000-0000-0000-0000-000000000001"
TARGET_MEMBER_UUID = "00000000-0000-0000-0000-000000000002"

PATH_PARAM_DEFAULTS: dict[str, str] = {
    "id": DEFAULT_UUID,
    "member_id": DEFAULT_UUID,
    "module_key": "assets",
    "key": "inapp",
    "installation_id": DEFAULT_UUID,
    "delivery_id": DEFAULT_UUID,
    "notification_id": DEFAULT_UUID,
    "grant_id": DEFAULT_UUID,
    "category_id": DEFAULT_UUID,
    "field_id": DEFAULT_UUID,
    "manufacturer_id": DEFAULT_UUID,
    "supplier_id": DEFAULT_UUID,
    "asset_id": DEFAULT_UUID,
}

REQUIRED_QUERY_PARAMS: dict[str, dict[str, Any]] = {
    "/api/v1/role-grants": {"member_id": DEFAULT_UUID},
    "/api/auth/mock/authorize": {"redirect_uri": "http://localhost:5173/auth/callback"},
}

DEFAULT_PAYLOADS: dict[tuple[str, str], dict[str, Any]] = {
    ("POST", "/api/v1/locations"): {"code": "loc-1", "name": "Test Location", "type": "building"},
    ("PATCH", "/api/v1/locations/{id}"): {"name": "Updated Location", "version": 1},
    ("PUT", "/api/v1/locations/{id}"): {"name": "Updated Location", "version": 1},
    ("POST", "/api/v1/locations/{id}/move"): {"new_parent_id": None, "version": 1},
    ("POST", "/api/v1/org-units"): {"code": "tou-1", "name": "Test Org Unit", "type": "division"},
    ("PATCH", "/api/v1/org-units/{id}"): {"name": "Updated Org Unit", "version": 1},
    ("PUT", "/api/v1/org-units/{id}"): {"name": "Updated Org Unit", "version": 1},
    ("POST", "/api/v1/org-units/{id}/move"): {"new_parent_id": TARGET_MEMBER_UUID, "version": 1},
    ("POST", "/api/v1/org-units/{id}/archive"): {"version": 1},
    ("POST", "/api/v1/teams"): {"code": "team-1", "name": "Test Team", "type": "maintenance"},
    ("PATCH", "/api/v1/teams/{id}"): {"name": "Updated Team", "version": 1},
    ("PUT", "/api/v1/teams/{id}"): {"name": "Updated Team", "version": 1},
    ("POST", "/api/v1/teams/{id}/archive"): {"version": 1},
    ("POST", "/api/v1/teams/{id}/members"): {"member_id": TARGET_MEMBER_UUID, "team_role": "member"},
    ("PATCH", "/api/v1/teams/{id}/members/{member_id}"): {"team_role": "lead"},
    ("PUT", "/api/v1/teams/{id}/members/{member_id}"): {"team_role": "lead"},
    ("POST", "/api/v1/role-grants"): {
        "member_id": TARGET_MEMBER_UUID,
        "role_key": "technician",
        "scope_type": "organization",
    },
    ("POST", "/api/v1/import/preview"): {"org_units": [], "teams": [], "members": []},
    ("POST", "/api/v1/import/commit"): {"org_units": [], "teams": [], "members": []},
    ("PATCH", "/api/v1/organizations/settings"): {"locale": "en-US"},
    ("POST", "/api/v1/notification-channels/installations"): {
        "channel_key": "inapp",
        "display_name": "Default In-App Channel",
    },
    ("PATCH", "/api/v1/notification-channels/installations/{installation_id}"): {
        "display_name": "Renamed Channel",
        "version": 1,
    },
    ("PUT", "/api/v1/me/notification-preferences"): {
        "changes": [{"event_type": "test.event", "channel_key": "inapp", "enabled": True}]
    },
    ("POST", "/api/auth/session"): {
        "code": "demo-admin",
        "redirect_uri": "http://localhost:5173/auth/callback",
    },
    ("POST", "/api/v1/asset-categories"): {"code": "cat-1", "name": "Test Category"},
    ("PATCH", "/api/v1/asset-categories/{category_id}"): {"name": "Updated Category", "version": 1},
    ("POST", "/api/v1/asset-categories/{category_id}/move"): {
        "new_parent_id": TARGET_MEMBER_UUID,
        "version": 1,
    },
    ("POST", "/api/v1/asset-categories/{category_id}/archive"): {"version": 1},
    ("POST", "/api/v1/asset-categories/{category_id}/custom-fields"): {
        "key": "test_field",
        "label": "Test Field",
        "field_type": "text",
    },
    ("PATCH", "/api/v1/asset-categories/{category_id}/custom-fields/{field_id}"): {
        "label": "Updated Field",
        "version": 1,
    },
    ("POST", "/api/v1/asset-categories/{category_id}/custom-fields/{field_id}/archive"): {"version": 1},
    ("POST", "/api/v1/assets"): {
        "name": "Test Asset",
        "category_id": DEFAULT_UUID,
        "owner_org_unit_id": DEFAULT_UUID,
    },
    ("PATCH", "/api/v1/assets/{asset_id}"): {"name": "Updated Asset", "version": 1},
    ("POST", "/api/v1/manufacturers"): {"name": "Test Manufacturer"},
    ("PATCH", "/api/v1/manufacturers/{manufacturer_id}"): {"name": "Updated Manufacturer", "version": 1},
    ("POST", "/api/v1/manufacturers/{manufacturer_id}/archive"): {"version": 1},
    ("POST", "/api/v1/suppliers"): {"name": "Test Supplier"},
    ("PATCH", "/api/v1/suppliers/{supplier_id}"): {"name": "Updated Supplier", "version": 1},
    ("POST", "/api/v1/suppliers/{supplier_id}/archive"): {"version": 1},
}


def build_route_url(path_template: str) -> str:
    """Format a path template (e.g. `/api/v1/locations/{id}`) with default dummy parameter values."""
    url = path_template
    for key, value in PATH_PARAM_DEFAULTS.items():
        placeholder = f"{{{key}}}"
        if placeholder in url:
            url = url.replace(placeholder, value)
    return url


def get_query_params(path_template: str) -> dict[str, Any]:
    """Retrieve required query parameters for a route template."""
    return REQUIRED_QUERY_PARAMS.get(path_template, {})


def get_request_body(method: str, path_template: str) -> dict[str, Any] | None:
    """Retrieve a schema-valid request body for a route method and path template."""
    return DEFAULT_PAYLOADS.get((method.upper(), path_template))
