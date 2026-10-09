// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Shared fixtures and helpers for the asset screens' tests: a mock of the API contract (P8-06 to P8-09) and a
// renderer that mounts a page at its route with the providers it needs.
import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { vi } from "vitest";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router";
import { ToastProvider } from "@/app/ToastProvider";
import { setAccessToken } from "@/lib/auth";
import type { GrantedPermission } from "@/lib/permissions";
import { newQueryClient } from "@/test/render";
import { envelope, makeMe, meHandler, server } from "@/test/server";

export const ORG_SCOPE = [{ scope_type: "organization" as const, scope_id: null }];

export function grant(permission: string): GrantedPermission {
  return { permission, scopes: ORG_SCOPE };
}

export const CATEGORY = {
  id: "cat-1",
  name: "Pumps",
  parent_id: null,
  path: "pumps",
  code: "pumps",
  tag_prefix: null,
  default_criticality: "high",
  responsible_team_id: null,
  status: "active",
  version: 1,
};

export function fieldDef(
  key: string,
  type: string,
  over: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    id: `fd-${key}`,
    category_id: "cat-1",
    key,
    label: key.charAt(0).toUpperCase() + key.slice(1),
    field_type: type,
    is_required: false,
    rules: {},
    is_unique: false,
    is_encrypted: false,
    position: 0,
    status: "active",
    version: 1,
    ...over,
  };
}

export function assetDetail(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "ast-1",
    organization_id: "org-1",
    tag: "AST-0001",
    name: "Pump one",
    category_id: "cat-1",
    category_name: "Pumps",
    model: "X100",
    manufacturer_id: null,
    manufacturer_name: null,
    supplier_id: null,
    supplier_name: null,
    serial_number: null,
    owner_org_unit_id: "ou-1",
    owner_org_unit_name: "Plant A",
    owner_org_unit_path: "plant_a",
    location_id: null,
    location_name: null,
    holder: null,
    status: "in_use",
    criticality: "high",
    purchase_date: null,
    purchase_cost: null,
    warranty_end: null,
    custom_fields: {},
    encrypted_fields: {},
    notes: null,
    parent: null,
    component_count: 0,
    version: 4,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-02T00:00:00Z",
    ...over,
  };
}

/** The lookups every asset screen reads, with one category, one org unit and the given custom fields. */
export function mockLookups(fields: Record<string, unknown>[] = []): void {
  server.use(
    http.get("/api/v1/asset-categories", () =>
      HttpResponse.json(envelope({ items: [CATEGORY], next_cursor: null })),
    ),
    http.get("/api/v1/asset-categories/cat-1/custom-fields", () =>
      HttpResponse.json(envelope({ items: fields, next_cursor: null })),
    ),
    http.get("/api/v1/org-units", () =>
      HttpResponse.json(envelope([{ id: "ou-1", name: "Plant A", parent_id: null, path: "plant_a" }])),
    ),
    http.get("/api/v1/manufacturers", () =>
      HttpResponse.json(
        envelope({
          items: [{ id: "mf-1", name: "Acme", code: null, notes: null, status: "active", version: 1 }],
          next_cursor: null,
        }),
      ),
    ),
    http.get("/api/v1/suppliers", () => HttpResponse.json(envelope({ items: [], next_cursor: null }))),
    http.get("/api/v1/assets/vocabulary", () =>
      HttpResponse.json(
        envelope({
          statuses: [
            { key: "in_use", label: "In service", category: "in_use" },
            { key: "in_repair", label: "Under repair", category: "unavailable" },
          ],
          criticality: ["low", "medium", "high"],
        }),
      ),
    ),
  );
}

export function setViewport(wide: boolean): void {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: wide,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
}

export function clearViewport(): void {
  // @ts-expect-error jsdom has no matchMedia; remove the mock so other tests see the default
  delete window.matchMedia;
}

const Probe: React.FC = () => <output data-testid="path">{useLocation().pathname}</output>;

/** Mount `element` at `route`, entered at `url`, signed in with `permissions` and the `assets` module. */
export function renderAt(
  element: React.ReactElement,
  route: string,
  url: string,
  permissions: GrantedPermission[],
): ReturnType<typeof createMemoryRouter> {
  setAccessToken("test-token");
  server.use(meHandler(makeMe({ permissions, installed_modules: ["assets"] })));
  const router = createMemoryRouter(
    [
      {
        path: route,
        element: (
          <>
            {element}
            <Probe />
          </>
        ),
      },
      { path: "*", element: <Probe /> },
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
