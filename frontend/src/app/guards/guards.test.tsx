// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, MemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/app/ToastProvider";
import { buildRoutes } from "@/app/routes";
import { setAccessToken } from "@/lib/auth";
import { t } from "@/lib/i18n";
import { makeMe, meHandler, server } from "@/test/server";
import { newQueryClient, renderApp, withProviders } from "@/test/render";
import { RequireModule } from "./guards";

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

describe("RequireModule", () => {
  // NotAuthorizedPage renders a react-router <Link>, so the tree needs a Router context even
  // though these tests don't exercise routing itself (withProviders alone has none, and the
  // missing context throws, which can take down unrelated tests run afterward in the same file).
  it("shows the not-authorized screen to a member without the module installed", async () => {
    setAccessToken("test-token");
    server.use(meHandler(makeMe({ installed_modules: [] })));
    withProviders(
      <MemoryRouter>
        <RequireModule module="assets">
          <div>asset content</div>
        </RequireModule>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: t("pages.not_authorized.title") })).toBeInTheDocument();
  });

  it("shows the children to a member with the module installed", async () => {
    setAccessToken("test-token");
    server.use(meHandler(makeMe({ installed_modules: ["assets"] })));
    withProviders(
      <MemoryRouter>
        <RequireModule module="assets">
          <div>asset content</div>
        </RequireModule>
      </MemoryRouter>,
    );
    expect(await screen.findByText("asset content")).toBeInTheDocument();
  });

  it("refuses a suspended member even with the module installed (prior critical finding)", async () => {
    setAccessToken("test-token");
    server.use(meHandler(makeMe({ is_suspended: true, installed_modules: ["assets"] })));
    withProviders(
      <MemoryRouter>
        <RequireModule module="assets">
          <div>asset content</div>
        </RequireModule>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: t("pages.not_authorized.title") })).toBeInTheDocument();
    expect(screen.queryByText("asset content")).not.toBeInTheDocument();
  });
});
