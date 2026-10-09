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

describe("AssetCategoriesPage categories", () => {
  it("shows the tree with indentation and settings", async () => {
    renderPage();
    const tree = await screen.findByRole("list", { name: t("assets.categories.tree_label") });
    expect(within(tree).getByText("Pumps")).toBeInTheDocument();
    expect(within(tree).getByText("Valves")).toBeInTheDocument();
    expect(within(tree).getByText(/High/)).toBeInTheDocument();
  });

  it("creates a category under a parent", async () => {
    server.use(
      http.post("/api/v1/asset-categories", async ({ request }) => {
        record(request, (await request.json()) as Record<string, unknown>);
        return HttpResponse.json(envelope({ ...CATEGORY, id: "cat-3", name: "Motors", code: "motors" }), {
          status: 201,
        });
      }),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: t("assets.categories.new") }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(new RegExp(`^${t("assets.categories.code")}`)), "motors");
    await user.type(within(dialog).getByLabelText(new RegExp(`^${t("assets.form.name")}`)), "Motors");
    await user.selectOptions(within(dialog).getByLabelText(t("assets.categories.parent")), "cat-1");
    await user.click(within(dialog).getByRole("button", { name: t("assets.categories.create") }));
    await waitFor(() => {
      expect(bodies).toEqual([
        {
          url: "/api/v1/asset-categories",
          method: "POST",
          body: { code: "motors", name: "Motors", parent_id: "cat-1" },
        },
      ]);
    });
  });

  it("renames a category with its version", async () => {
    server.use(
      http.patch("/api/v1/asset-categories/cat-2", async ({ request }) => {
        record(request, (await request.json()) as Record<string, unknown>);
        return HttpResponse.json(envelope({ ...CHILD, name: "Control valves", version: 2 }));
      }),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: t("assets.categories.edit_named", { name: "Valves" }) }),
    );
    const dialog = await screen.findByRole("dialog");
    const name = within(dialog).getByLabelText(new RegExp(`^${t("assets.form.name")}`));
    await user.clear(name);
    await user.type(name, "Control valves");
    await user.click(within(dialog).getByRole("button", { name: t("assets.form.save_changes") }));
    await waitFor(() => {
      expect(bodies[0]?.body).toEqual({ version: 1, name: "Control valves" });
    });
  });

  it("moves a category, offering neither itself nor its descendants", async () => {
    server.use(
      http.post("/api/v1/asset-categories/cat-1/move", async ({ request }) => {
        record(request, (await request.json()) as Record<string, unknown>);
        return HttpResponse.json(envelope(CATEGORY));
      }),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: t("assets.categories.move_named", { name: "Pumps" }) }),
    );
    const dialog = await screen.findByRole("dialog");
    // Pumps has one descendant (Valves) and is itself excluded: nothing is left to move under.
    expect(within(dialog).queryByRole("option", { name: "Valves" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("option", { name: "Pumps" })).not.toBeInTheDocument();
  });

  it("shows the API's blocker when a category cannot be archived", async () => {
    server.use(
      http.post("/api/v1/asset-categories/cat-2/archive", () =>
        HttpResponse.json(
          { code: "asset_category.archive_blocked", detail: "12 assets still use this category." },
          { status: 409 },
        ),
      ),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: t("assets.categories.archive_named", { name: "Valves" }) }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: t("assets.categories.archive") }));
    expect(await within(dialog).findByText("12 assets still use this category.")).toBeInTheDocument();
  });

  it("archives with the record's version", async () => {
    server.use(
      http.post("/api/v1/asset-categories/cat-2/archive", async ({ request }) => {
        record(request, (await request.json()) as Record<string, unknown>);
        return HttpResponse.json(envelope({ ...CHILD, status: "archived", version: 2 }));
      }),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: t("assets.categories.archive_named", { name: "Valves" }) }),
    );
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: t("assets.categories.archive"),
      }),
    );
    await waitFor(() => {
      expect(bodies).toEqual([
        { url: "/api/v1/asset-categories/cat-2/archive", method: "POST", body: { version: 1 } },
      ]);
    });
  });
});

describe("AssetCategoriesPage custom fields", () => {
  it("lists a selected category's fields and creates one", async () => {
    server.use(
      http.post("/api/v1/asset-categories/cat-1/custom-fields", async ({ request }) => {
        record(request, (await request.json()) as Record<string, unknown>);
        return HttpResponse.json(envelope(fieldDef("tier", "select")), { status: 201 });
      }),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Pumps" }));
    expect(await screen.findByText("Serial")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: t("assets.categories.field_new") }));
    const dialog = await screen.findByRole("dialog");
    await user.type(
      within(dialog).getByLabelText(new RegExp(`^${t("assets.categories.field_key")}`)),
      "tier",
    );
    await user.type(
      within(dialog).getByLabelText(new RegExp(`^${t("assets.categories.field_label")}`)),
      "Tier",
    );
    await user.selectOptions(within(dialog).getByLabelText(t("assets.categories.field_type")), "select");
    await user.click(within(dialog).getByRole("button", { name: t("assets.categories.field_create") }));
    expect(await within(dialog).findByText(t("assets.categories.errors.options"))).toBeInTheDocument();

    await user.type(
      within(dialog).getByLabelText(new RegExp(`^${t("assets.categories.options")}`)),
      "gold{enter}silver",
    );
    await user.click(within(dialog).getByLabelText(t("assets.categories.is_encrypted")));
    await user.click(within(dialog).getByRole("button", { name: t("assets.categories.field_create") }));
    await waitFor(() => {
      expect(bodies[0]?.body).toEqual({
        key: "tier",
        label: "Tier",
        field_type: "select",
        is_required: false,
        is_unique: false,
        is_encrypted: true,
        position: 0,
        options: ["gold", "silver"],
      });
    });
  });

  it("edits a field: the key is fixed and only changes are sent", async () => {
    server.use(
      http.patch("/api/v1/asset-categories/cat-1/custom-fields/fd-serial", async ({ request }) => {
        record(request, (await request.json()) as Record<string, unknown>);
        return HttpResponse.json(envelope(fieldDef("serial", "text", { label: "Serial no." })));
      }),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Pumps" }));
    await user.click(
      await screen.findByRole("button", {
        name: t("assets.categories.field_edit_named", { name: "Serial" }),
      }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText(new RegExp(`^${t("assets.categories.field_key")}`))).toBeDisabled();
    const label = within(dialog).getByLabelText(new RegExp(`^${t("assets.categories.field_label")}`));
    await user.clear(label);
    await user.type(label, "Serial no.");
    await user.click(within(dialog).getByRole("button", { name: t("assets.form.save_changes") }));
    await waitFor(() => {
      expect(bodies[0]?.body).toEqual({ version: 1, label: "Serial no." });
    });
  });

  it("archives a field", async () => {
    server.use(
      http.post("/api/v1/asset-categories/cat-1/custom-fields/fd-serial/archive", async ({ request }) => {
        record(request, (await request.json()) as Record<string, unknown>);
        return HttpResponse.json(envelope(fieldDef("serial", "text", { status: "archived" })));
      }),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Pumps" }));
    await user.click(
      await screen.findByRole("button", {
        name: t("assets.categories.field_archive_named", { name: "Serial" }),
      }),
    );
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: t("assets.categories.archive"),
      }),
    );
    await waitFor(() => {
      expect(bodies[0]?.body).toEqual({ version: 1 });
    });
  });
});

describe("AssetCategoriesPage manufacturers and suppliers", () => {
  it("lists manufacturers and creates a supplier", async () => {
    server.use(
      http.post("/api/v1/suppliers", async ({ request }) => {
        record(request, (await request.json()) as Record<string, unknown>);
        return HttpResponse.json(
          envelope({ id: "sp-1", name: "Parts Ltd", code: null, notes: null, status: "active", version: 1 }),
          { status: 201 },
        );
      }),
    );
    renderPage();
    const user = userEvent.setup();
    const list = await screen.findByRole("list", { name: t("assets.categories.manufacturers") });
    expect(within(list).getByText("Acme")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: t("assets.categories.supplier_new") }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(new RegExp(`^${t("assets.form.name")}`)), "Parts Ltd");
    await user.click(within(dialog).getByRole("button", { name: t("assets.categories.create") }));
    await waitFor(() => {
      expect(bodies).toEqual([{ url: "/api/v1/suppliers", method: "POST", body: { name: "Parts Ltd" } }]);
    });
  });

  it("archives a manufacturer with its version", async () => {
    server.use(
      http.post("/api/v1/manufacturers/mf-1/archive", async ({ request }) => {
        record(request, (await request.json()) as Record<string, unknown>);
        return HttpResponse.json(
          envelope({ id: "mf-1", name: "Acme", code: "acme", notes: null, status: "archived", version: 3 }),
        );
      }),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: t("assets.categories.archive_named", { name: "Acme" }) }),
    );
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: t("assets.categories.archive"),
      }),
    );
    await waitFor(() => {
      expect(bodies[0]?.body).toEqual({ version: 2 });
    });
  });
});
