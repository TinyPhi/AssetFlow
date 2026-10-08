// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { setAccessToken, setRefreshHandler } from "@/lib/auth";
import { envelope, server } from "@/test/server";
import { apiFetch, isProblemError, newIdempotencyKey, ProblemError, queryKeys } from ".";

describe("apiFetch", () => {
  it("unwraps the success envelope and uses the /api/v1 base", async () => {
    server.use(http.get("/api/v1/things", () => HttpResponse.json(envelope({ items: [1, 2] }))));
    await expect(apiFetch<{ items: number[] }>("/things")).resolves.toEqual({ items: [1, 2] });
  });

  it("sends the access token as a Bearer header and no header when signed out", async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get("/api/v1/who", ({ request }) => {
        seen.push(request.headers.get("authorization"));
        return HttpResponse.json(envelope(null));
      }),
    );
    await apiFetch("/who");
    setAccessToken("abc");
    await apiFetch("/who");
    expect(seen).toEqual([null, "Bearer abc"]);
  });

  it("sends a JSON body and an Idempotency-Key on a write", async () => {
    let received: { key: string | null; type: string | null; body: unknown } | undefined;
    server.use(
      http.post("/api/v1/things", async ({ request }) => {
        received = {
          key: request.headers.get("idempotency-key"),
          type: request.headers.get("content-type"),
          body: await request.json(),
        };
        return HttpResponse.json(envelope({ id: "1" }), { status: 201 });
      }),
    );
    const key = newIdempotencyKey();
    await apiFetch("/things", { method: "POST", body: { name: "x" }, idempotencyKey: key });
    expect(received).toEqual({ key, type: "application/json", body: { name: "x" } });
  });

  it("generates a fresh idempotency key each time", () => {
    expect(newIdempotencyKey()).not.toEqual(newIdempotencyKey());
  });

  it("maps a problem response to a typed ProblemError", async () => {
    server.use(
      http.post("/api/v1/things", () =>
        HttpResponse.json(
          {
            code: "validation.invalid_field",
            detail: "One or more fields are invalid.",
            request_id: "req-9",
            errors: [{ field: "body.name", message: "required" }, { nope: true }],
          },
          { status: 422, headers: { "content-type": "application/problem+json" } },
        ),
      ),
    );
    const error = await apiFetch("/things", { method: "POST", body: {} }).catch((e: unknown) => e);
    expect(isProblemError(error)).toBe(true);
    expect(error).toMatchObject({
      code: "validation.invalid_field",
      status: 422,
      detail: "One or more fields are invalid.",
      requestId: "req-9",
      errors: [{ field: "body.name", message: "required" }],
    });
  });

  it("still throws a ProblemError when the failure has no problem body", async () => {
    server.use(http.get("/api/v1/broken", () => new HttpResponse("oops", { status: 502 })));
    const error = await apiFetch("/broken").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ProblemError);
    expect(error).toMatchObject({ status: 502, code: "unknown" });
  });

  it("returns undefined for a 204", async () => {
    server.use(http.delete("/api/v1/things/1", () => new HttpResponse(null, { status: 204 })));
    await expect(apiFetch("/things/1", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("rejects a success response that is not an envelope", async () => {
    server.use(http.get("/api/v1/odd", () => HttpResponse.json({ items: [] })));
    await expect(apiFetch("/odd")).rejects.toMatchObject({ code: "invalid_response" });
  });
});

describe("401 handling", () => {
  it("refreshes once and retries with the new token", async () => {
    const tokens: (string | null)[] = [];
    server.use(
      http.get("/api/v1/secret", ({ request }) => {
        const token = request.headers.get("authorization");
        tokens.push(token);
        if (token === "Bearer fresh") return HttpResponse.json(envelope({ ok: true }));
        return HttpResponse.json({ code: "auth.unauthorized" }, { status: 401 });
      }),
    );
    setAccessToken("stale");
    setRefreshHandler(() => Promise.resolve("fresh"));
    await expect(apiFetch("/secret")).resolves.toEqual({ ok: true });
    expect(tokens).toEqual(["Bearer stale", "Bearer fresh"]);
  });

  it("shares one refresh between concurrent 401 answers (single flight)", async () => {
    let refreshes = 0;
    server.use(
      http.get("/api/v1/secret", ({ request }) =>
        request.headers.get("authorization") === "Bearer fresh"
          ? HttpResponse.json(envelope({ ok: true }))
          : HttpResponse.json({ code: "auth.unauthorized" }, { status: 401 }),
      ),
    );
    setAccessToken("stale");
    setRefreshHandler(async () => {
      refreshes += 1;
      await new Promise((resolve) => setTimeout(resolve, 20));
      return "fresh";
    });
    await Promise.all([apiFetch("/secret"), apiFetch("/secret"), apiFetch("/secret")]);
    expect(refreshes).toBe(1);
  });

  it("gives up with the 401 problem when there is no refresh handler", async () => {
    server.use(
      http.get("/api/v1/secret", () => HttpResponse.json({ code: "auth.unauthorized" }, { status: 401 })),
    );
    await expect(apiFetch("/secret")).rejects.toMatchObject({ status: 401, code: "auth.unauthorized" });
  });

  it("gives up and signs out when the refresh fails, retrying nothing", async () => {
    let calls = 0;
    server.use(
      http.get("/api/v1/secret", () => {
        calls += 1;
        return HttpResponse.json({ code: "auth.unauthorized" }, { status: 401 });
      }),
    );
    setAccessToken("stale");
    setRefreshHandler(() => Promise.reject(new Error("refresh failed")));
    await expect(apiFetch("/secret")).rejects.toMatchObject({ status: 401 });
    expect(calls).toBe(1);
  });
});

describe("queryKeys", () => {
  it("builds stable keys from one place", () => {
    expect(queryKeys.me()).toEqual(["me"]);
    expect(queryKeys.me()).toEqual(queryKeys.me());
  });
});
