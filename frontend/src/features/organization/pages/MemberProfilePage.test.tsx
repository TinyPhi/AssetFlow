// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { envelope, server } from "@/test/server";
import { renderApp } from "@/test/render";

const MEMBER_READ = {
  permission: "member.read",
  scopes: [{ scope_type: "organization" as const, scope_id: null }],
};

describe("MemberProfilePage", () => {
  it("sends the bearer token and renders the member's real profile", async () => {
    let sawAuthorization = false;
    server.use(
      http.get("/api/v1/members/:memberId", ({ request }) => {
        sawAuthorization = request.headers.get("authorization") === "Bearer test-token";
        return HttpResponse.json(
          envelope({
            id: "m-1",
            display_name: "Real Member",
            status: "active",
            is_suspended: false,
            org_units: [],
            teams: [],
          }),
        );
      }),
    );

    renderApp("/members/m-1", { me: { permissions: [MEMBER_READ] } });

    expect(await screen.findByRole("heading", { name: "Real Member" })).toBeInTheDocument();
    expect(sawAuthorization).toBe(true);
  });

  it("shows a real error, not a fabricated demo profile, when the request fails", async () => {
    server.use(
      http.get("/api/v1/members/:memberId", () =>
        HttpResponse.json({ code: "internal.error" }, { status: 500 }),
      ),
    );

    renderApp("/members/m-1", { me: { permissions: [MEMBER_READ] } });

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("Ada Lovelace")).not.toBeInTheDocument();
  });
});
