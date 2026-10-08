// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/app/ToastProvider";
import { buildRoutes } from "@/app/routes";
import { setAccessToken } from "@/lib/auth";
import { t } from "@/lib/i18n";
import { newQueryClient, renderApp } from "@/test/render";
import { server } from "@/test/server";

const ORG_READ = {
  permission: "org_unit.read",
  scopes: [{ scope_type: "organization" as const, scope_id: null }],
};

describe("RequireAuth", () => {
  it("sends a signed-out visitor to sign in, from any private path", async () => {
    renderApp("/teams", { signedIn: false });
    expect(await screen.findByRole("heading", { name: t("pages.sign_in.title") })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: t("nav.menu.label") })).not.toBeInTheDocument();
  });

  it("lets the public sign-in page render without a session", async () => {
    renderApp("/sign-in", { signedIn: false });
    expect(await screen.findByRole("heading", { name: t("pages.sign_in.title") })).toBeInTheDocument();
    expect(await screen.findByText(t("app.shell.health_ok"))).toBeInTheDocument();
  });

  it("shows the private layout once there is a session", async () => {
    renderApp("/");
    expect(await screen.findByRole("navigation", { name: t("nav.menu.label") })).toBeInTheDocument();
  });
});

describe("RequirePermission", () => {
  it("shows the not-authorized screen to a member without the permission", async () => {
    renderApp("/organization", { me: { permissions: [] } });
    expect(await screen.findByRole("heading", { name: t("pages.not_authorized.title") })).toBeInTheDocument();
  });

  it("shows the screen to a member who holds the permission", async () => {
    renderApp("/organization", { me: { permissions: [ORG_READ] } });
    expect(await screen.findByRole("heading", { name: t("nav.items.organization") })).toBeInTheDocument();
  });

  it("refuses a suspended member even with the permission", async () => {
    renderApp("/organization", { me: { is_suspended: true, permissions: [ORG_READ] } });
    expect(await screen.findByRole("heading", { name: t("pages.not_authorized.title") })).toBeInTheDocument();
  });

  it("shows a loading state first and an error with retry when the profile cannot be read", async () => {
    setAccessToken("test-token");
    server.use(http.get("/api/v1/me", () => HttpResponse.json({ code: "internal.error" }, { status: 500 })));
    render(
      <QueryClientProvider client={newQueryClient()}>
        <ToastProvider>
          <RouterProvider router={createMemoryRouter(buildRoutes(), { initialEntries: ["/organization"] })} />
        </ToastProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: t("ui.error.retry") })).toBeInTheDocument();
  });
});
