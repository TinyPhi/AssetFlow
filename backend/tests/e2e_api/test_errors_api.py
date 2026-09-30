# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""RFC 9457 problem responses and X-Request-ID handling through the real app (§C1.5.1, §C4.5)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from app.core.problems import ConflictError, FieldError
from app.main import create_app

DOC_PREFIX = "https://github.com/tinyphi/assetflow/blob/main/docs/reference/error-codes.md#"
LEAKY_TEXT = "SELECT * FROM members WHERE password='hunter2'"


def _app() -> FastAPI:
    app = create_app()

    @app.get("/api/v1/_probe/items/{item_id}")
    async def get_item(item_id: int, limit: int = 10) -> dict[str, int]:
        return {"item_id": item_id, "limit": limit}

    @app.get("/api/v1/_probe/boom")
    async def boom() -> None:
        raise RuntimeError(LEAKY_TEXT)

    @app.get("/api/v1/_probe/conflict")
    async def conflict() -> None:
        raise ConflictError(
            "The work order changed since you loaded it.",
            errors=[FieldError(field="version", message="expected 4, current 5")],
        )

    return app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _assert_problem(resp: httpx.Response, status: int, code: str) -> dict[str, object]:
    assert resp.status_code == status
    assert resp.headers["content-type"].startswith("application/problem+json")
    body: dict[str, object] = resp.json()
    assert body["status"] == status
    assert body["code"] == code
    assert body["type"] == DOC_PREFIX + code
    assert body["request_id"] == resp.headers["x-request-id"]
    assert isinstance(body["title"], str)
    assert isinstance(body["detail"], str)
    return body


async def test_unknown_route_is_problem_json(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/does-not-exist")
    body = _assert_problem(resp, 404, "http.not_found")
    assert body["instance"] == "/api/v1/does-not-exist"


async def test_wrong_method_is_problem_json(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/ping")
    _assert_problem(resp, 405, "http.method_not_allowed")
    assert "GET" in resp.headers["allow"]


async def test_validation_has_errors_extension_without_input_echo(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/_probe/items/not-a-number", params={"limit": "hunter2"})
    body = _assert_problem(resp, 422, "validation.invalid_field")
    errors = body["errors"]
    assert isinstance(errors, list)
    assert {e["field"] for e in errors} == {"path.item_id", "query.limit"}
    for entry in errors:
        assert set(entry) == {"field", "message"}
    assert "hunter2" not in resp.text


async def test_unexpected_exception_is_generic_and_logged(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="assetflow.http"):
        resp = await client.get("/api/v1/_probe/boom")
    body = _assert_problem(resp, 500, "internal.error")
    assert "hunter2" not in resp.text
    assert "RuntimeError" not in resp.text
    assert "Traceback" not in resp.text
    assert body["detail"] == "An unexpected error occurred. Quote the request id when reporting it."
    records = [r for r in caplog.records if r.getMessage() == "http.unhandled_exception"]
    assert len(records) == 1
    assert records[0].exc_info is not None
    assert getattr(records[0], "request_id", None) == body["request_id"]


async def test_domain_error_keeps_its_detail_and_field_errors(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/_probe/conflict")
    body = _assert_problem(resp, 409, "resource.conflict")
    assert body["detail"] == "The work order changed since you loaded it."
    assert body["errors"] == [{"field": "version", "message": "expected 4, current 5"}]


async def test_valid_client_request_id_is_kept_normalized(client: httpx.AsyncClient) -> None:
    sent = "0192F5A0-1B2C-7D3E-8F40-123456789ABC"
    resp = await client.get("/api/v1/ping", headers={"X-Request-ID": sent})
    assert resp.headers["x-request-id"] == sent.lower()
    assert resp.json()["request_id"] == sent.lower()


@pytest.mark.parametrize(
    "sent",
    [
        "not-a-uuid",
        "0192f5a0-1b2c-7d3e-8f40-123456789abc" + "x" * 30,
        "{" + "0192f5a0-1b2c-7d3e-8f40-123456789abc" * 2 + "}",
        "<script>alert(1)</script>",
    ],
)
async def test_invalid_client_request_id_is_replaced(client: httpx.AsyncClient, sent: str) -> None:
    resp = await client.get("/api/v1/does-not-exist", headers={"X-Request-ID": sent})
    got = resp.headers["x-request-id"]
    assert got != sent
    assert UUID(got).version == 7
    assert resp.json()["request_id"] == got


async def test_single_request_id_header(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/_probe/boom")
    assert len(resp.headers.get_list("x-request-id")) == 1
