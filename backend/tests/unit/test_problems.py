# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""Unit tests for the error registry, problem responses and the success envelope (§C1.5, §C1.5.1)."""

from __future__ import annotations

import json
import re

import pytest

from app.core import problems
from app.core.envelope import success_response
from app.core.problems import (
    ERROR_REGISTRY,
    FieldError,
    ProblemError,
    SecretsUnavailableError,
    UnauthorizedError,
    ValidationFailedError,
    problem_response,
    problem_type_url,
)

CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def test_every_code_is_area_dot_reason_and_unique() -> None:
    codes = [cls.code for cls in ERROR_REGISTRY]
    assert len(codes) == len(set(codes))
    for cls in ERROR_REGISTRY:
        assert CODE_PATTERN.match(cls.code), cls.code
        assert 400 <= cls.status_code <= 599
        assert cls.title
        assert cls.default_detail
        assert cls.description != ProblemError.description


def test_every_problem_error_subclass_is_registered() -> None:
    subclasses = {
        obj
        for obj in vars(problems).values()
        if isinstance(obj, type) and issubclass(obj, ProblemError) and obj is not ProblemError
    }
    assert subclasses == set(ERROR_REGISTRY)


def test_required_codes() -> None:
    assert (UnauthorizedError.code, UnauthorizedError.status_code) == ("auth.unauthorized", 401)
    assert (SecretsUnavailableError.code, SecretsUnavailableError.status_code) == (
        "platform.secrets_unavailable",
        503,
    )
    assert ValidationFailedError.code == "validation.invalid_field"


def test_validation_class_does_not_shadow_pydantic() -> None:
    assert not hasattr(problems, "ValidationError")


def test_config_error_is_reexported_from_config() -> None:
    from app.core import config  # noqa: PLC0415

    assert problems.ConfigError is config.ConfigError


def test_type_url_points_at_error_codes_reference() -> None:
    assert problem_type_url("auth.unauthorized") == (
        "https://github.com/tinyphi/assetflow/blob/main/docs/reference/error-codes.md#auth.unauthorized"
    )


def test_problem_response_shape() -> None:
    rid = "0192f5a0-1b2c-7d3e-8f40-123456789abc"
    resp = problem_response(
        status=422,
        code="validation.invalid_field",
        title="Validation failed",
        detail="One or more fields are invalid.",
        instance="/api/v1/assets",
        request_id=rid,
        errors=[FieldError(field="body.name", message="Field required")],
    )
    assert resp.status_code == 422
    assert resp.media_type == "application/problem+json"
    assert resp.headers["x-request-id"] == rid
    assert json.loads(bytes(resp.body)) == {
        "type": problem_type_url("validation.invalid_field"),
        "title": "Validation failed",
        "status": 422,
        "detail": "One or more fields are invalid.",
        "instance": "/api/v1/assets",
        "code": "validation.invalid_field",
        "request_id": rid,
        "errors": [{"field": "body.name", "message": "Field required"}],
    }


def test_problem_error_defaults_and_headers() -> None:
    err = UnauthorizedError()
    assert err.detail == UnauthorizedError.default_detail
    assert err.headers == {"WWW-Authenticate": "Bearer"}
    assert SecretsUnavailableError().errors is None


@pytest.mark.parametrize("data", [{"a": 1}, [1, 2], None])
def test_success_envelope(data: object) -> None:
    res = success_response(data, message="Fetched", request_id="req-1")
    assert res["status"] == "success"
    assert res["status_code"] == 200
    assert res["message"] == "Fetched"
    assert res["request_id"] == "req-1"
    assert res["data"] == data
    assert res["timestamp"].endswith("Z")
