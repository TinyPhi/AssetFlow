// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { t } from "@/lib/i18n";
import { envelope, server } from "@/test/server";
import { CATEGORY, fieldDef, grant, renderAt } from "../test-support";
import { AssetCategoriesPage } from "./AssetCategoriesPage";

const CHILD = {
  ...CATEGORY,
  id: "cat-2",
  name: "Valves",
  code: "valves",
  path: "pumps.valves",
  parent_id: "cat-1",
  default_criticality: null,
};

let bodies: { url: string; method: string; body: Record<string, unknown> }[];
let fields: Record<string, unknown>[];

function record(request: Request, body: Record<string, unknown>): void {
  bodies.push({ url: new URL(request.url).pathname, method: request.method, body });
}

beforeEach(() => {
  bodies = [];
  fields = [fieldDef("serial", "text", { is_required: true })];
  server.use(
    http.get("/api/v1/asset-categories", () =>
      HttpResponse.json(envelope({ items: [CATEGORY, CHILD], next_cursor: null })),
    ),
    http.get("/api/v1/asset-categories/cat-1/custom-fields", () =>
      HttpResponse.json(envelope({ items: fields, next_cursor: null })),
    ),
    http.get("/api/v1/manufacturers", () =>
      HttpResponse.json(
        envelope({
          items: [{ id: "mf-1", name: "Acme", code: "acme", notes: null, status: "active", version: 2 }],
          next_cursor: null,
        }),
      ),
    ),
    http.get("/api/v1/suppliers", () => HttpResponse.json(envelope({ items: [], next_cursor: null }))),
    http.get("/api/v1/assets/vocabulary", () =>
      HttpResponse.json(envelope({ statuses: [], criticality: ["low", "high"] })),
    ),
  );
});

function renderPage(): void {
  renderAt(<AssetCategoriesPage />, "/admin/asset-categories", "/admin/asset-categories", [
    grant("asset.update"),
  ]);
}

