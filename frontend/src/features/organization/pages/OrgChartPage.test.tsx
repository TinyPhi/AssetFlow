// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { envelope, server } from "@/test/server";
import { renderApp } from "@/test/render";

const ORG_UNIT_READ = {
  permission: "org_unit.read",
  scopes: [{ scope_type: "organization" as const, scope_id: null }],
};

describe("OrgChartPage", () => {
  it("sends the bearer token and renders the real org units", async () => {
    let sawAuthorization = false;
    server.use(
      http.get("/api/v1/org-units", ({ request }) => {
        sawAuthorization = request.headers.get("authorization") === "Bearer test-token";
        return HttpResponse.json(envelope([{ id: "real-unit", name: "Real Division", member_count: 3 }]));
      }),
    );

    renderApp("/organization", { me: { permissions: [ORG_UNIT_READ] } });

    expect(await screen.findByText("Real Division")).toBeInTheDocument();
    expect(sawAuthorization).toBe(true);
    expect(screen.queryByText("Headquarters")).not.toBeInTheDocument();
  });

  it("shows a real error, not a fabricated demo tree, when the request fails", async () => {
    server.use(
      http.get("/api/v1/org-units", () => HttpResponse.json({ code: "internal.error" }, { status: 500 })),
    );

    renderApp("/organization", { me: { permissions: [ORG_UNIT_READ] } });

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("Engineering")).not.toBeInTheDocument();
  });
});
