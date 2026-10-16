// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { t } from "@/lib/i18n";
import { renderApp } from "@/test/render";

const ASSET_READ = {
  permission: "asset.read",
  scopes: [{ scope_type: "organization" as const, scope_id: null }],
};

describe("RequireModule", () => {
  it("shows not-authorized when the module is not installed, even with the permission", async () => {
    renderApp("/assets", { me: { permissions: [ASSET_READ], installed_modules: [] } });
    expect(await screen.findByRole("heading", { name: t("pages.not_authorized.title") })).toBeInTheDocument();
  });

  it("shows the screen when the module is installed and the permission held", async () => {
    renderApp("/assets", { me: { permissions: [ASSET_READ], installed_modules: ["assets"] } });
    expect(await screen.findByRole("heading", { name: t("assets.list.title") })).toBeInTheDocument();
  });

  it("checks the module before the permission it wraps, so neither alone is enough", async () => {
    renderApp("/assets", { me: { permissions: [], installed_modules: ["assets"] } });
    expect(await screen.findByRole("heading", { name: t("pages.not_authorized.title") })).toBeInTheDocument();
  });
});
