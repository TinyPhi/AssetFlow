# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Custom-field `regex` rules run on RE2: linear-time matching, never backtracking (§B10, §C5.4).

A custom-field pattern is written by an organization admin (or a domain template), so it is
untrusted. Python's `re` backtracks: `^(a+)+$` against a long `a…a!` value takes minutes and, run on
the event loop, stalls the API process for every organization. RE2 guarantees time linear in the
input, so no pattern can do that. RE2 has no look-arounds or back-references; such a pattern is
refused when the definition (or the template) is saved, with the engine's reason.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import re2

__all__ = ["MAX_REGEX_PATTERN_LENGTH", "compile_field_regex"]

#: A regex pattern over 200 characters is refused when the definition is saved (P8-07).
MAX_REGEX_PATTERN_LENGTH = 200


def _options() -> Any:
    options = re2.Options()
    options.log_errors = False  # RE2 would otherwise print the rejected pattern to stderr
    return options


_OPTIONS = _options()


@lru_cache(maxsize=256)
def compile_field_regex(pattern: str) -> Any:
    """Compile a `text` field's `regex` rule once, on RE2.

    Raises ``ValueError`` for an over-long pattern or one RE2 cannot compile (including Python-only
    syntax such as look-arounds and back-references).
    """
    if len(pattern) > MAX_REGEX_PATTERN_LENGTH:
        raise ValueError(f"regex must be at most {MAX_REGEX_PATTERN_LENGTH} characters")
    try:
        return re2.compile(pattern, _OPTIONS)
    except re2.error as exc:
        reason = (
            exc.args[0].decode("utf-8", "replace") if exc.args and isinstance(exc.args[0], bytes) else exc
        )
        raise ValueError(f"regex is not supported: {reason}") from exc
