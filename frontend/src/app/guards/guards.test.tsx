// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { t } from "@/lib/i18n";
import { renderApp } from "@/test/render";
import { server } from "@/test/server";

const ORG_READ = {
  permission: "org_unit.read",
  scopes: [{ scope_type: "organization" as const, scope_id: null }],
};
const ASSET_READ = {
  permission: "asset.read",
  scopes: [{ scope_type: "organization" as const, scope_id: null }],
};

describe("RequireAuth", () => {
  it("sends a signed-out visitor to sign in, from any private path", async () => {
    renderApp("/teams", { signedIn: false });
    expect(await screen.findByRole("heading", { name: t("pages.sign_in.title") })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: t("nav.label") })).not.toBeInTheDocument();
  });

  it("lets the public sign-in page render without a session", async () => {
    renderApp("/sign-in", { signedIn: false });
    expect(await screen.findByRole("heading", { name: t("pages.sign_in.title") })).toBeInTheDocument();
    expect(await screen.findByText(t("app.shell.health_ok"))).toBeInTheDocument();
  });

  it("shows the private layout once there is a session", async () => {
    renderApp("/");
    expect(await screen.findByRole("navigation", { name: t("nav.label") })).toBeInTheDocument();
  });
});

describe("RequirePermission", () => {
  it("shows the not-authorized screen to a member without the permission", async () => {
    renderApp("/organization", { me: { permissions: [] } });
    expect(await screen.findByRole("heading", { name: t("pages.not_authorized.title") })).toBeInTheDocument();
    expect(screen.queryByText(t("pages.coming_soon"))).not.toBeInTheDocument();
  });

  it("shows the screen to a member who holds the permission", async () => {
    renderApp("/organization", { me: { permissions: [ORG_READ] } });
    expect(await screen.findByRole("heading", { name: t("nav.organization") })).toBeInTheDocument();
    expect(screen.getByText(t("pages.coming_soon"))).toBeInTheDocument();
  });

  it("refuses a suspended member even with the permission", async () => {
    renderApp("/organization", { me: { is_suspended: true, permissions: [ORG_READ] } });
    expect(await screen.findByRole("heading", { name: t("pages.not_authorized.title") })).toBeInTheDocument();
  });

  it("shows a loading state first and an error with retry when the profile cannot be read", async () => {
    server.use(http.get("/api/v1/me", () => HttpResponse.json({ code: "internal.error" }, { status: 500 })));
    renderApp("/organization", { me: { permissions: [ORG_READ] } });
    server.use(http.get("/api/v1/me", () => HttpResponse.json({ code: "internal.error" }, { status: 500 })));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: t("ui.error.retry") })).toBeInTheDocument();
  });
});

describe("RequireModule", () => {
  it("shows not-authorized when the module is not installed, even with the permission", async () => {
    renderApp("/assets", { me: { permissions: [ASSET_READ], installed_modules: [] } });
    expect(await screen.findByRole("heading", { name: t("pages.not_authorized.title") })).toBeInTheDocument();
  });

  it("shows the screen when the module is installed and the permission held", async () => {
    renderApp("/assets", { me: { permissions: [ASSET_READ], installed_modules: ["assets"] } });
    expect(await screen.findByRole("heading", { name: t("nav.assets") })).toBeInTheDocument();
  });

  it("checks the module before the permission it wraps, so neither alone is enough", async () => {
    renderApp("/assets", { me: { permissions: [], installed_modules: ["assets"] } });
    expect(await screen.findByRole("heading", { name: t("pages.not_authorized.title") })).toBeInTheDocument();
  });
});
