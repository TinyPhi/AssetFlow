# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Every public repository list method takes a `ScopeFilter` (§C4.4, §B5.3).

A list query without a scope filter is a leak waiting to happen, so the rule is enforced by
reflection over every `*Repository` class in `app.modules`: a public `list*` method must have a
`scope_filter: ScopeFilter` parameter, unless it is in `EXEMPT` with the reason it is safe.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import typing

import pytest

import app.modules
from app.core.permissions import ScopeFilter

#: Methods that list rows that are not scope-filtered by design, with the reason.
EXEMPT: dict[str, str] = {
    "TeamMemberRepository.list_by_team": "P5: lists one team after the service checked that team in scope",
    "SavedViewRepository.list_own": "personal data: always filtered by the owning member id",
}


def all_repository_list_methods() -> list[tuple[str, typing.Callable[..., object]]]:
    found: list[tuple[str, typing.Callable[..., object]]] = []
    for info in pkgutil.walk_packages(app.modules.__path__, "app.modules."):
        if not (info.name.endswith(".repository") or info.name.endswith(".saved_views")):
            continue
        module = importlib.import_module(info.name)
        for cls_name, cls in inspect.getmembers(module, inspect.isclass):
            if not cls_name.endswith("Repository") or cls.__module__ != module.__name__:
                continue
            for name, method in inspect.getmembers(cls, inspect.isfunction):
                if name.startswith("list"):
                    found.append((f"{cls_name}.{name}", method))
    return found


def _takes_scope_filter(method: typing.Callable[..., object]) -> bool:
    hints = typing.get_type_hints(method)
    return any(hint is ScopeFilter for hint in hints.values())


def test_the_enumeration_finds_the_asset_repository() -> None:
    names = {name for name, _ in all_repository_list_methods()}
    assert "AssetRepository.list_assets" in names
    assert "SavedViewRepository.list_own" in names


@pytest.mark.parametrize(("name", "method"), all_repository_list_methods())
def test_repository_list_method_takes_a_scope_filter(name: str, method: typing.Callable[..., object]) -> None:
    if name in EXEMPT:
        return
    assert _takes_scope_filter(method), f"{name} lists rows without a ScopeFilter parameter (§C4.4)"


def test_exemptions_are_not_stale() -> None:
    names = {name for name, _ in all_repository_list_methods()}
    assert set(EXEMPT) <= names
