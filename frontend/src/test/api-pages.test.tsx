// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Every page reads the API through apiFetch, so it sends the session's bearer token, and shows a
// real error (never made-up demo data) when the API fails (PR 292 review follow-up: nine pages
// called fetch() directly with no Authorization header and fell back to fabricated rows).
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { envelope, server } from "@/test/server";
import { renderApp } from "@/test/render";

const org = (permission: string) => ({
  permission,
  scopes: [{ scope_type: "organization" as const, scope_id: null }],
});

interface PageCase {
  name: string;
  path: string;
  permission: string;
  endpoint: string;
  data: unknown;
  shows: string;
  neverShows: string;
}

const PAGES: PageCase[] = [
  {
    name: "teams",
    path: "/teams",
    permission: "team.read",
    endpoint: "/api/v1/teams",
    data: [{ id: "t1", name: "Night Shift", member_count: 2 }],
    shows: "Night Shift",
    neverShows: "Core Infrastructure",
  },
  {
    name: "locations",
    path: "/locations",
    permission: "location.read",
    endpoint: "/api/v1/locations",
    data: [{ id: "l1", name: "North Yard", parent_id: null }],
    shows: "North Yard",
    neverShows: "Main Campus",
  },
  {
    name: "modules",
    path: "/admin/modules",
    permission: "role_grant.read",
    endpoint: "/api/v1/modules",
    data: [{ key: "assets", is_installed: false, dependencies: [] }],
    shows: "Available",
    neverShows: "Installed",
  },
  {
    name: "notifications",
    path: "/notifications",
    permission: "notification.read",
    endpoint: "/api/v1/notifications",
    data: {
      items: [
        {
          id: "n1",
          event_type: "member.invited",
          title_key: "x",
          body: "Real inbox row",
          read_at: null,
          created_at: "2026-03-01T12:00:00Z",
        },
      ],
      next_cursor: null,
    },
    shows: "Real inbox row",
    neverShows: "Welcome to AssetFlow",
  },
  {
    name: "delivery log",
    path: "/admin/notification-channels/deliveries",
    permission: "notification_delivery.read",
    endpoint: "/api/v1/notification-channels/deliveries",
    data: {
      items: [
        {
          id: "d1",
          channel_key: "email",
          target: "ops@example.org",
          status: "delivered",
          attempts: 1,
          error_code: null,
          created_at: "2026-03-01T12:00:00Z",
        },
      ],
      next_cursor: null,
    },
    shows: "ops@example.org",
    neverShows: "member.invited",
  },
  {
    name: "notification channels",
    path: "/admin/notification-channels",
    permission: "notification_channel.read",
    endpoint: "/api/v1/notification-channels/installations",
    data: [{ id: "c1", channel_key: "email", display_name: "Real Relay", enabled: true }],
    shows: "Real Relay",
    neverShows: "Corporate Email Relay",
  },
];

describe.each(PAGES)("$name page", (page) => {
  it("sends the bearer token and renders the API's rows", async () => {
    let authorization: string | null = null;
    server.use(
      http.get(page.endpoint, ({ request }) => {
        authorization = request.headers.get("authorization");
        return HttpResponse.json(envelope(page.data));
      }),
    );

    renderApp(page.path, { me: { permissions: [org(page.permission)] } });

    // DataTable renders a table and narrow-screen cards, so a value may appear twice.
    expect((await screen.findAllByText(page.shows)).length).toBeGreaterThan(0);
    expect(authorization).toBe("Bearer test-token");
    expect(screen.queryByText(page.neverShows)).not.toBeInTheDocument();
  });

  it("shows a real error, not made-up rows, when the request fails", async () => {
    server.use(http.get(page.endpoint, () => HttpResponse.json({ code: "internal.error" }, { status: 500 })));

    renderApp(page.path, { me: { permissions: [org(page.permission)] } });

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(page.neverShows)).not.toBeInTheDocument();
  });
});

describe("organization settings page", () => {
  it("shows an error instead of silent defaults when settings cannot be read", async () => {
    server.use(
      http.get("/api/v1/organizations/settings", () =>
        HttpResponse.json({ code: "internal.error" }, { status: 500 }),
      ),
    );

    renderApp("/admin/settings", { me: { permissions: [org("role_grant.read")] } });

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("saves only the fields the form edits, with the bearer token", async () => {
    let sent: unknown = null;
    let authorization: string | null = null;
    server.use(
      http.get("/api/v1/organizations/settings", () =>
        HttpResponse.json(envelope({ locale: "en-US", timezone: "UTC", provisioning: "open", extra_key: 1 })),
      ),
      http.patch("/api/v1/organizations/settings", async ({ request }) => {
        authorization = request.headers.get("authorization");
        sent = await request.json();
        return HttpResponse.json(envelope({ locale: "en-US", timezone: "UTC", provisioning: "open" }));
      }),
    );

    renderApp("/admin/settings", {
      me: { permissions: [org("role_grant.read"), org("organization.settings_manage")] },
    });

    await userEvent.click(await screen.findByRole("button", { name: "Save Settings" }));

    await waitFor(() => {
      expect(sent).toEqual({ locale: "en-US", timezone: "UTC", provisioning: "open" });
    });
    expect(authorization).toBe("Bearer test-token");
  });
});

describe("notification bell", () => {
  it("shows the API's unread count (the API answers {unread: n})", async () => {
    server.use(
      http.get("/api/v1/notifications/unread-count", () => HttpResponse.json(envelope({ unread: 7 }))),
    );

    renderApp("/", { me: { permissions: [org("notification.read")] } });

    const bell = await screen.findByRole("button", { name: "Notifications, 7 unread" });
    expect(within(bell).getByText("7")).toBeInTheDocument();
  });
});

describe("notification preferences page", () => {
  it("renders the API's matrix and saves only the changed cell, with its version", async () => {
    let sent: unknown = null;
    const matrix = {
      channels: ["inapp", "email"],
      events: [
        {
          event_type: "member.invited",
          channels: [
            { channel_key: "inapp", enabled: true, version: 0, locked: true },
            { channel_key: "email", enabled: true, version: 3, locked: false },
          ],
        },
      ],
    };
    server.use(
      http.get("/api/v1/me/notification-preferences", () => HttpResponse.json(envelope(matrix))),
      http.put("/api/v1/me/notification-preferences", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(envelope(matrix));
      }),
    );

    renderApp("/settings/notifications");

    const locked = await screen.findByRole("checkbox", { name: "member.invited by inapp" });
    expect(locked).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: "member.invited by email" }));
    await userEvent.click(screen.getByRole("button", { name: "Save Preferences" }));

    await waitFor(() => {
      expect(sent).toEqual({
        changes: [{ event_type: "member.invited", channel_key: "email", enabled: false, version: 3 }],
      });
    });
  });

  it("shows an error instead of made-up events when preferences cannot be read", async () => {
    server.use(
      http.get("/api/v1/me/notification-preferences", () =>
        HttpResponse.json({ code: "internal.error" }, { status: 500 }),
      ),
    );

    renderApp("/settings/notifications");

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("Work Order Assigned")).not.toBeInTheDocument();
  });
});
