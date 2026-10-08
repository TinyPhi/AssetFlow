# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Static checks of the nginx configuration in deploy/nginx (AF-014, AF-032).

nginx does not inherit `add_header` from the server block into a location that has its own
`add_header`, so each location has to include the shared security-header file. These tests read the
real files; they start no nginx.

Run: make test-scripts
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

NGINX_DIR = Path(__file__).resolve().parent.parent.parent / "deploy" / "nginx"
SERVER_FILES = ["default.conf", "default.conf.template"]
HEADERS = NGINX_DIR / "security-headers.conf"
INCLUDE = "include /etc/nginx/snippets/security-headers.conf;"
LOCATION = re.compile(r"^\s*location\s[^{]*\{", re.MULTILINE)


def _locations(text: str) -> list[str]:
    """The body of every top-level `location` block of a server file."""
    bodies = []
    for match in LOCATION.finditer(text):
        depth, index = 1, match.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(text[index], 0)
            index += 1
        bodies.append(text[match.end() : index - 1])
    return bodies


def _directives(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


@pytest.mark.parametrize("name", SERVER_FILES)
def test_every_location_includes_the_security_headers(name: str) -> None:
    locations = _locations((NGINX_DIR / name).read_text(encoding="utf-8"))
    assert len(locations) >= 5
    for body in locations:
        assert INCLUDE in _directives(body), body


@pytest.mark.parametrize("name", SERVER_FILES)
def test_security_headers_are_defined_only_in_the_include(name: str) -> None:
    text = (NGINX_DIR / name).read_text(encoding="utf-8")
    added = [d for d in _directives(text) if d.startswith("add_header ")]
    assert added, "the cache headers are still added by the locations"
    assert all(d.split()[1] == "Cache-Control" for d in added), added
    assert any(d.startswith("set $csp ") for d in _directives(text))


def test_the_include_has_every_header_including_hsts() -> None:
    text = HEADERS.read_text(encoding="utf-8")
    names = {d.split()[1] for d in _directives(text) if d.startswith("add_header ")}
    assert names == {
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "Cross-Origin-Opener-Policy",
        "Strict-Transport-Security",
        "Content-Security-Policy",
    }
    hsts = next(d for d in _directives(text) if "Strict-Transport-Security" in d)
    assert "max-age=31536000" in hsts and hsts.endswith("always;")


@pytest.mark.parametrize("name", SERVER_FILES)
def test_forwarded_for_is_the_peer_address_not_an_appended_chain(name: str) -> None:
    text = (NGINX_DIR / name).read_text(encoding="utf-8")
    assert "proxy_add_x_forwarded_for" not in text
    values = re.findall(r"proxy_set_header\s+X-Forwarded-For\s+(\S+);", text)
    assert values and set(values) == {"$remote_addr"}
