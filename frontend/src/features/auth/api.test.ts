// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { exchangeSession, logoutSession, refreshSessionToken } from "./api";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200 });
}

function sentHeaders(): Headers {
  const init = fetchMock.mock.calls[0]?.[1];
  return new Headers(init?.headers);
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("cookie-bound auth requests", () => {
  it("sends X-Requested-With: AssetFlow on refresh", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ access_token: "t", expires_in: 60 }));
    await refreshSessionToken();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/auth/refresh");
    expect(sentHeaders().get("X-Requested-With")).toBe("AssetFlow");
  });

  it("sends X-Requested-With: AssetFlow on logout", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await logoutSession();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/auth/logout");
    expect(sentHeaders().get("X-Requested-With")).toBe("AssetFlow");
  });
});

describe("exchangeSession", () => {
  it("posts exactly code, redirect_uri, code_verifier, state and nonce", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ access_token: "t", expires_in: 60 }));
    await exchangeSession("the-code", "http://localhost:5173/auth/callback", {
      codeVerifier: "v".repeat(43),
      state: "s".repeat(32),
      nonce: "n".repeat(32),
    });
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe("/api/auth/session");
    expect(init?.method).toBe("POST");
    const body = JSON.parse(init?.body as string) as Record<string, string>;
    expect(Object.keys(body).sort()).toEqual(
      ["code", "code_verifier", "nonce", "redirect_uri", "state"].sort(),
    );
    expect(body).toEqual({
      code: "the-code",
      redirect_uri: "http://localhost:5173/auth/callback",
      code_verifier: "v".repeat(43),
      state: "s".repeat(32),
      nonce: "n".repeat(32),
    });
  });
});
