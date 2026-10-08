# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Telemetry scrubber: PII and credentials out of values, exception text and log records (§B6.1).

Standard library only, so every provider (and the root logging filter) can use it without the
OpenTelemetry extra.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import traceback
from itertools import pairwise
from typing import Any

REDACTED = "[REDACTED]"

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9_\-\.=~+/]+", re.IGNORECASE)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}(?:\.[A-Za-z0-9_-]*)?")
_PHONE_RE = re.compile(
    r"(?<![\w.+-])(?:\+\s?\d[\d\s().-]{6,}\d|\(?\d{2,5}\)?[\s.-]\d[\d\s().-]{4,}\d)(?![\w-])"
)
_IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.]*\w)")
_IPV6_RE = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:])")
_PREFIXED_TOKEN_RE = re.compile(
    r"\b(?:sk|pk|rk)[-_][A-Za-z0-9_\-]{16,}|\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{16,}"
    r"|\bxox[abprs]-[A-Za-z0-9-]{10,}|\bAKIA[0-9A-Z]{16}\b|\b(?:hvs|hvb|bao)[._][A-Za-z0-9_.\-]{16,}"
)
_LONG_TOKEN_RE = re.compile(r"(?<![\w\-+/=])[A-Za-z0-9_\-+/=]{32,}(?![\w\-+/=])")
_UUID_RE = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
_DATE_RE = re.compile(r"\d{4}[-./]\d{2}[-./]\d{2}|\d{2}[-./]\d{2}[-./]\d{4}")

# Whole-word keys: a key is sensitive when one of its words (split on non-alphanumerics and
# camelCase) is listed, or when two neighbouring words form a listed pair. "tokenizer" and
# "monkey" are not sensitive; "access_token" and "apiKey" are (AF-048).
_SENSITIVE_WORDS = frozenset(
    {"password", "passwd", "secret", "token", "authorization", "apikey", "credential", "cookie"}
)
_SENSITIVE_PAIRS = frozenset(
    {("api", "key"), ("client", "secret"), ("set", "cookie"), ("private", "key"), ("access", "key")}
)
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def is_sensitive_key(key: object) -> bool:
    """True when ``key`` names a credential, by whole word."""
    words = [w for w in _SPLIT_RE.split(_CAMEL_RE.sub("_", str(key)).lower()) if w]
    singular = [w[:-1] if w.endswith("s") and len(w) > 3 else w for w in words]
    if any(w in _SENSITIVE_WORDS for w in singular):
        return True
    return any(pair in _SENSITIVE_PAIRS for pair in pairwise(singular))


def _ipv4(match: re.Match[str]) -> str:
    text = match.group(0)
    try:
        ipaddress.IPv4Address(text)
    except ValueError:
        return text
    return "[IP_REDACTED]"


def _ipv6(match: re.Match[str]) -> str:
    text = match.group(0)
    try:
        ipaddress.IPv6Address(text)
    except ValueError:
        return text
    return "[IP_REDACTED]"


def _phone(match: re.Match[str]) -> str:
    text = match.group(0)
    digits = sum(c.isdigit() for c in text)
    if digits < 8 or digits > 15 or _DATE_RE.search(text):
        return text
    return "[PHONE_REDACTED]"


def _long_token(match: re.Match[str]) -> str:
    text = match.group(0)
    if _UUID_RE.fullmatch(text):
        return text
    if any(c.isdigit() for c in text) and any(c.isalpha() for c in text):
        return "[TOKEN_REDACTED]"
    return text


def scrub_text(text: str) -> str:
    """Scrub one string: bearer values, JWTs, emails, IPs, phones and token-shaped strings."""
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _JWT_RE.sub("[JWT_REDACTED]", text)
    text = _PREFIXED_TOKEN_RE.sub("[TOKEN_REDACTED]", text)
    text = _EMAIL_RE.sub("[EMAIL_REDACTED]", text)
    text = _IPV6_RE.sub(_ipv6, text)
    text = _IPV4_RE.sub(_ipv4, text)
    text = _PHONE_RE.sub(_phone, text)
    return _LONG_TOKEN_RE.sub(_long_token, text)


def scrub_value(val: Any) -> Any:
    """Scrub PII, emails, tokens, and credentials from a value (§B6.1 rule 6)."""
    if isinstance(val, str):
        return scrub_text(val)
    if isinstance(val, dict):
        return {k: REDACTED if is_sensitive_key(k) else scrub_value(v) for k, v in val.items()}
    if isinstance(val, (list, tuple, set)):
        return [scrub_value(x) for x in val]
    return val


def scrub_exception(exc: BaseException) -> str:
    """The exception's formatted traceback with every sensitive value scrubbed (AF-035)."""
    return scrub_text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip())


class ScrubbingLogFilter(logging.Filter):
    """Scrub the message, its arguments and any exception text of a log record (AF-035)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            message = str(record.msg)
        record.msg = scrub_text(message)
        record.args = None
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = scrub_exception(record.exc_info[1])
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = scrub_text(record.exc_text)
        return True


_FILTER = ScrubbingLogFilter()
_factory_installed = False


def install_root_log_filter() -> None:
    """Scrub every log record of the process, whichever logger or handler it reaches. Idempotent.

    A filter on the root logger would skip records of child loggers and one on handlers would
    miss handlers added later, so the scrubber wraps the record factory.
    """
    global _factory_installed  # noqa: PLW0603 - process-wide singleton by design
    if _factory_installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        _FILTER.filter(record)
        return record

    logging.setLogRecordFactory(factory)
    _factory_installed = True
