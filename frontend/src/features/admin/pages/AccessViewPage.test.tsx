// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { envelope, server } from "@/test/server";
import { renderApp } from "@/test/render";

const GRANT_READ = {
  permission: "role_grant.read",
  scopes: [{ scope_type: "organization" as const, scope_id: null }],
};

describe("AccessViewPage", () => {
  it("sends the bearer token and renders the member's real effective permissions", async () => {
    let sawAuthorization = false;
    server.use(
      http.get("/api/v1/members/:memberId/access", ({ request }) => {
        sawAuthorization = request.headers.get("authorization") === "Bearer test-token";
        return HttpResponse.json(
          envelope({
            member_id: "m-1",
            permissions: [
              { permission: "asset.read", scopes: [{ scope_type: "organization", scope_id: null }] },
            ],
          }),
        );
      }),
    );

    renderApp("/admin/access/m-1", { me: { permissions: [GRANT_READ] } });

    const table = await screen.findByRole("table", { hidden: true });
    expect(within(table).getByText("asset.read")).toBeInTheDocument();
    expect(sawAuthorization).toBe(true);
  });

  it("shows a real error, not fabricated demo permissions, when the request fails", async () => {
    server.use(
      http.get("/api/v1/members/:memberId/access", () =>
        HttpResponse.json({ code: "internal.error" }, { status: 500 }),
      ),
    );

    renderApp("/admin/access/m-1", { me: { permissions: [GRANT_READ] } });

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("org_unit.read")).not.toBeInTheDocument();
  });
});
