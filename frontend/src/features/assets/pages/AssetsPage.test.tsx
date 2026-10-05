// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/app/ToastProvider";
import { setAccessToken } from "@/lib/auth";
import { t } from "@/lib/i18n";
import { envelope, makeMe, meHandler, server } from "@/test/server";
import { newQueryClient } from "@/test/render";
import { AssetsPage } from "./AssetsPage";

const READ = { permission: "asset.read", scopes: [{ scope_type: "organization" as const, scope_id: null }] };
const CREATE = {
  permission: "asset.create",
  scopes: [{ scope_type: "organization" as const, scope_id: null }],
};

function asset(n: number, over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: `0192f000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    organization_id: "0192f000-0000-7000-8000-0000000000aa",
    tag: `AST-${String(n).padStart(4, "0")}`,
    name: `Asset ${String(n)}`,
    category_id: "cat-1",
    category_name: "Pumps",
    model: null,
    manufacturer_id: null,
    manufacturer_name: null,
    serial_number: null,
    owner_org_unit_id: "ou-1",
    owner_org_unit_name: "Plant A",
    location_id: null,
    location_name: null,
    holder: null,
    status: "in_service",
    criticality: "high",
    warranty_end: null,
    purchase_date: null,
    custom_fields: {},
    version: 1,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-02T00:00:00Z",
    ...over,
  };
}

const requests: URL[] = [];

function listHandler(respond: (url: URL) => Record<string, unknown>): void {
  server.use(
    http.get("/api/v1/assets", ({ request }) => {
      const url = new URL(request.url);
      requests.push(url);
      return HttpResponse.json(envelope(respond(url)));
    }),
  );
}

function setViewport(wide: boolean): void {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: wide,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
}

const Probe: React.FC = () => <output data-testid="url">{useLocation().search}</output>;

function renderPage(
  url = "/assets",
  permissions: (typeof READ)[] = [READ],
): ReturnType<typeof createMemoryRouter> {
  setAccessToken("test-token");
  server.use(meHandler(makeMe({ permissions, installed_modules: ["assets"] })));
  const router = createMemoryRouter(
    [
      {
        path: "/assets",
        element: (
          <>
            <AssetsPage />
            <Probe />
          </>
        ),
      },
    ],
    { initialEntries: [url] },
  );
  render(
    <QueryClientProvider client={newQueryClient()}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return router;
}

beforeEach(() => {
  requests.length = 0;
  setViewport(true);
});

afterEach(() => {
  // @ts-expect-error jsdom has no matchMedia; remove the mock so other tests see the default
  delete window.matchMedia;
});

describe("AssetsPage states", () => {
  it("shows a skeleton while loading, then the rows", async () => {
    listHandler(() => ({ items: [asset(1), asset(2)], next_cursor: null, total: null }));
    renderPage();
    expect(screen.getByRole("status", { busy: true })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Asset 1" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Asset 2" })).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("shows an error with a retry that loads again", async () => {
    let fail = true;
    server.use(
      http.get("/api/v1/assets", () =>
        fail
          ? HttpResponse.json({ code: "boom", status: 500 }, { status: 500 })
          : HttpResponse.json(envelope({ items: [asset(1)], next_cursor: null, total: null })),
      ),
    );
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent(t("assets.list.load_failed"));
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: t("ui.error.retry") }));
    expect(await screen.findByRole("link", { name: "Asset 1" })).toBeInTheDocument();
  });

  it("shows the empty state with New asset only to a member who may create", async () => {
    listHandler(() => ({ items: [], next_cursor: null, total: null }));
    renderPage("/assets", [READ]);
    expect(await screen.findByText(t("assets.list.empty_title"))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: t("assets.list.new_asset") })).not.toBeInTheDocument();
  });

  it("offers New asset (header and empty state) when asset.create is held", async () => {
    listHandler(() => ({ items: [], next_cursor: null, total: null }));
    renderPage("/assets", [READ, CREATE]);
    expect(await screen.findByText(t("assets.list.empty_title"))).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: t("assets.list.new_asset") })).toHaveLength(2);
  });

  it("says nothing matched, with a way to clear, when a search finds nothing", async () => {
    listHandler(() => ({ items: [], next_cursor: null, total: null }));
    renderPage("/assets?q=zzz");
    expect(await screen.findByText(t("assets.list.no_match_title"))).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: t("assets.list.clear_filters") }));
    await waitFor(() => {
      expect(screen.getByTestId("url")).toHaveTextContent("");
    });
    expect(screen.getByRole("searchbox")).toHaveValue("");
  });
});

describe("AssetsPage search, filters and URL", () => {
  it("writes the debounced search text to the URL and requests it", async () => {
    listHandler(() => ({ items: [asset(1)], next_cursor: null, total: null }));
    renderPage();
    await screen.findByRole("link", { name: "Asset 1" });
    await userEvent.type(screen.getByRole("searchbox", { name: t("assets.list.search_label") }), "pump");
    await waitFor(() => {
      expect(screen.getByTestId("url")).toHaveTextContent("?q=pump");
    });
    await waitFor(() => {
      expect(requests.some((u) => u.searchParams.get("q") === "pump")).toBe(true);
    });
  });

  it("restores search and filters from the URL (refresh keeps state)", async () => {
    listHandler(() => ({ items: [asset(1)], next_cursor: null, total: null }));
    renderPage("/assets?q=pump&status=in_service&sort=name");
    expect(await screen.findByRole("searchbox")).toHaveValue("pump");
    await screen.findByRole("link", { name: "Asset 1" });
    const last = requests[requests.length - 1];
    expect(last?.searchParams.get("q")).toBe("pump");
    expect(last?.searchParams.getAll("status")).toEqual(["in_service"]);
    expect(last?.searchParams.get("sort")).toBe("name");
    expect(
      screen.getByRole("button", {
        name: t("assets.chips.remove", { filter: t("assets.chips.status", { value: "In service" }) }),
      }),
    ).toBeInTheDocument();
  });

  it("deselecting a filter chip removes it from the URL and the request", async () => {
    listHandler(() => ({ items: [asset(1)], next_cursor: null, total: null }));
    renderPage("/assets?status=in_service&status=repair");
    await screen.findByRole("link", { name: "Asset 1" });
    await userEvent.click(
      screen.getByRole("button", {
        name: t("assets.chips.remove", { filter: t("assets.chips.status", { value: "In service" }) }),
      }),
    );
    await waitFor(() => {
      expect(screen.getByTestId("url")).toHaveTextContent("?status=repair");
    });
    await userEvent.click(screen.getByRole("button", { name: t("assets.chips.clear_all") }));
    await waitFor(() => {
      expect(screen.getByTestId("url")).toHaveTextContent("");
    });
  });

  it("filters by a status checkbox from the filter panel", async () => {
    listHandler(() => ({
      items: [asset(1), asset(2, { status: "repair" })],
      next_cursor: null,
      total: null,
    }));
    renderPage();
    await screen.findByRole("link", { name: "Asset 1" });
    await userEvent.click(screen.getByRole("button", { name: t("assets.filters.toggle") }));
    await userEvent.click(await screen.findByRole("checkbox", { name: "Repair" }));
    await waitFor(() => {
      expect(screen.getByTestId("url")).toHaveTextContent("?status=repair");
    });
  });

  it("sorts by a column heading and shows the direction", async () => {
    listHandler(() => ({ items: [asset(1)], next_cursor: null, total: null }));
    renderPage();
    await screen.findByRole("link", { name: "Asset 1" });
    await userEvent.click(screen.getByRole("button", { name: t("assets.columns.name") }));
    await waitFor(() => {
      expect(screen.getByTestId("url")).toHaveTextContent("?sort=name");
    });
    expect(screen.getByRole("columnheader", { name: t("assets.columns.name") })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
    await userEvent.click(screen.getByRole("button", { name: t("assets.columns.name") }));
    await waitFor(() => {
      expect(screen.getByTestId("url")).toHaveTextContent("?sort=-name");
    });
  });
});

describe("AssetsPage cursor pages", () => {
  it("loads the next page with the cursor from the Load more button", async () => {
    listHandler((url) =>
      url.searchParams.get("after") === "c1"
        ? { items: [asset(2)], next_cursor: null, total: null }
        : { items: [asset(1)], next_cursor: "c1", total: null },
    );
    renderPage();
    await screen.findByRole("link", { name: "Asset 1" });
    await userEvent.click(screen.getByRole("button", { name: t("assets.list.load_more") }));
    expect(await screen.findByRole("link", { name: "Asset 2" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Asset 1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: t("assets.list.load_more") })).not.toBeInTheDocument();
  });
});

