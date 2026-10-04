// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// The mock API every component and hook test talks to (MSW). A test overrides a route with
// `server.use(...)`; an unmatched request fails the test, so nothing reaches a real network.
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import type { Me } from "@/lib/permissions";

export function makeMe(overrides: Partial<Me> = {}): Me {
  return {
    member_id: "0192f000-0000-7000-8000-000000000001",
    display_name: "Ada Lovelace",
    locale: "en",
    organization: { id: "0192f000-0000-7000-8000-0000000000aa", name: "Test Org", timezone: "UTC" },
    is_suspended: false,
    permissions: [],
    installed_modules: [],
    ...overrides,
  };
}

/** Success envelope as the API sends it (§C1.5). */
export function envelope(data: unknown): Record<string, unknown> {
  return {
    status: "success",
    status_code: 200,
    message: "OK",
    timestamp: "2026-03-01T12:00:00Z",
    request_id: "r1",
    data,
  };
}

export function meHandler(me: Me): ReturnType<typeof http.get> {
  return http.get("/api/v1/me", () => HttpResponse.json(envelope(me)));
}

export const server = setupServer(
  meHandler(makeMe()),
  http.get("/api/health", () => HttpResponse.json({ status: "ok" })),
);
