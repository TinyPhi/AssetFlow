// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { t } from "@/lib/i18n";
import type { GrantedPermission } from "@/lib/permissions";
import { renderApp } from "@/test/render";

function grant(permission: string): GrantedPermission {
  return { permission, scopes: [{ scope_type: "organization", scope_id: null }] };
}

async function navLinks(): Promise<string[]> {
  const nav = await screen.findByRole("navigation", { name: t("nav.menu.label") });
  return within(nav)
    .getAllByRole("link")
    .map((link) => link.textContent ?? "");
}

describe("navigation follows the member's permissions and installed modules", () => {
  it("shows only the always-available items to a member with no permissions", async () => {
    renderApp("/");
    await waitFor(async () => {
      expect(await navLinks()).toEqual([t("nav.items.dashboard"), t("nav.items.my_settings")]);
    });
  });

  it("shows an item only when its permission is held", async () => {
    renderApp("/", { me: { permissions: [grant("team.read"), grant("notification.read")] } });
    await waitFor(async () => {
      expect(await navLinks()).toEqual([
        t("nav.items.dashboard"),
        t("nav.items.teams"),
        t("nav.items.notifications"),
        t("nav.items.my_settings"),
      ]);
    });
  });

  it("hides a module's item until the module is installed, even with the permission", async () => {
    const permissions = [grant("asset.read"), grant("work_order.read")];
    const { unmount } = renderApp("/", { me: { permissions, installed_modules: [] } });
    await waitFor(async () => {
      expect(await navLinks()).toEqual([t("nav.items.dashboard"), t("nav.items.my_settings")]);
    });
    unmount();
    renderApp("/", { me: { permissions, installed_modules: ["assets"] } });
    await waitFor(async () => {
      expect(await navLinks()).toEqual([
        t("nav.items.dashboard"),
        t("nav.items.assets"),
        t("nav.items.my_settings"),
      ]);
    });
  });

  it("shows every item to a member who holds everything", async () => {
    renderApp("/", {
      me: {
        permissions: [
          "org_unit.read",
          "team.read",
          "member.read",
          "asset.read",
          "work_order.read",
          "notification.read",
          "role_grant.read",
        ].map(grant),
        installed_modules: ["assets", "maintenance"],
      },
    });
    await waitFor(async () => {
      expect(await navLinks()).toHaveLength(9);
    });
  });

  it("shows nothing to a suspended member's modules or permissions", async () => {
    renderApp("/", { me: { is_suspended: true, permissions: [grant("team.read")] } });
    await waitFor(async () => {
      expect(await navLinks()).toEqual([t("nav.items.dashboard"), t("nav.items.my_settings")]);
    });
  });
});

describe("responsive layout", () => {
  it("collapses the navigation behind a menu button that opens and closes it", async () => {
    const user = userEvent.setup();
    renderApp("/");
    const button = await screen.findByRole("button", { name: t("nav.menu.open") });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById("primary-navigation")).toHaveClass("hidden");
    await user.click(button);
    expect(screen.getByRole("button", { name: t("nav.menu.close") })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(document.getElementById("primary-navigation")).toHaveClass("block");
    await user.click(screen.getByRole("button", { name: t("nav.menu.close") }));
    expect(document.getElementById("primary-navigation")).toHaveClass("hidden");
  });

  it("closes the menu after a link is followed", async () => {
    const user = userEvent.setup();
    renderApp("/", { me: { permissions: [grant("team.read")] } });
    await user.click(await screen.findByRole("button", { name: t("nav.menu.open") }));
    await user.click(await screen.findByRole("link", { name: t("nav.items.teams") }));
    expect(await screen.findByRole("heading", { name: t("nav.items.teams") })).toBeInTheDocument();
    expect(document.getElementById("primary-navigation")).toHaveClass("hidden");
  });

  it("keeps every navigation link at least 44 px high and never gives the layout a fixed width", async () => {
    renderApp("/", { me: { permissions: [grant("team.read")] } });
    const nav = await screen.findByRole("navigation", { name: t("nav.menu.label") });
    for (const link of within(nav).getAllByRole("link")) {
      expect(link).toHaveClass("min-h-11");
    }
    const html = document.body.innerHTML;
    expect(html).not.toMatch(/\bw-\[\d+px\]|\bmin-w-\[\d+px\]|\bwidth:\s*\d+px/);
    expect(document.getElementById("main")).toHaveClass("min-w-0");
  });

  it("offers a skip link to the main content", async () => {
    renderApp("/");
    expect(await screen.findByRole("link", { name: t("nav.menu.skip_to_content") })).toHaveAttribute(
      "href",
      "#main",
    );
  });
});

describe("network status", () => {
  it("raises a toast when the network status changes", async () => {
    renderApp("/");
    await screen.findByRole("navigation", { name: t("nav.menu.label") });
    expect(screen.queryByText(t("app.toast.network_offline"))).not.toBeInTheDocument();
    act(() => {
      window.dispatchEvent(new Event("offline"));
    });
    expect(await screen.findByText(t("app.toast.network_offline"))).toBeInTheDocument();
    expect(screen.getAllByText(t("app.shell.offline")).length).toBeGreaterThan(0);
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    await waitFor(() => {
      expect(screen.getByText(t("app.toast.network_online"))).toBeInTheDocument();
    });
  });
});

describe("pages", () => {
  it("greets the member by name on the dashboard", async () => {
    renderApp("/");
    expect(
      await screen.findByText(new RegExp(`${t("pages.dashboard.welcome")}, Ada Lovelace`)),
    ).toBeInTheDocument();
  });

  it("shows not-found inside the layout for an unknown path", async () => {
    renderApp("/no-such-page");
    expect(await screen.findByRole("heading", { name: t("pages.not_found.title") })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: t("nav.menu.label") })).toBeInTheDocument();
  });
});
