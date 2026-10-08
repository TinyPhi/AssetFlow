// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { t } from "@/lib/i18n";
import { envelope, server } from "@/test/server";
import {
  assetDetail,
  clearViewport,
  fieldDef,
  grant,
  mockLookups,
  renderAt,
  setViewport,
} from "../test-support";
import { AssetDetailPage } from "./AssetDetailPage";

const FIELDS = [
  fieldDef("hostname", "text"),
  fieldDef("secret", "text", { is_encrypted: true }),
  fieldDef("owner_email", "text", { is_encrypted: true }),
];

const READ = grant("asset.read");
const UPDATE = grant("asset.update");

let asset: Record<string, unknown>;
let patches: Record<string, unknown>[];
let statusPosts: Record<string, unknown>[];
let transitions: { to_status: string; to_label: string; requires_reason: boolean }[];

function mockAsset(): void {
  server.use(
    http.get("/api/v1/assets/ast-1", () => HttpResponse.json(envelope(asset))),
    http.get("/api/v1/assets/ast-1/transitions", () => HttpResponse.json(envelope({ items: transitions }))),
    http.get("/api/v1/assets/ast-1/components", () => HttpResponse.json(envelope({ items: [] }))),
  );
}

function renderPage(permissions = [READ, UPDATE]): void {
  renderAt(<AssetDetailPage />, "/assets/:id", "/assets/ast-1", permissions);
}

beforeEach(() => {
  setViewport(true);
  patches = [];
  statusPosts = [];
  transitions = [
    { to_status: "in_repair", to_label: "Under repair", requires_reason: true },
    { to_status: "in_storage", to_label: "In storage", requires_reason: false },
  ];
  asset = assetDetail({
    custom_fields: { hostname: "pump-01" },
    encrypted_fields: { secret: { is_set: true }, owner_email: { is_set: false } },
  });
  mockLookups(FIELDS);
  mockAsset();
});

afterEach(clearViewport);

describe("AssetDetailPage header and details", () => {
  it("shows the tag, name, the template's status label and criticality", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "Pump one" })).toBeInTheDocument();
    expect(screen.getByText("AST-0001")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("In service")).toBeInTheDocument();
    });
    expect(screen.getByText(t("assets.detail.criticality_value", { level: "High" }))).toBeInTheDocument();
  });

  it("shows custom fields, and encrypted ones only as set or not set", async () => {
    renderPage();
    expect(await screen.findByText("pump-01")).toBeInTheDocument();
    expect(await screen.findByText(t("assets.detail.encrypted_set"))).toBeInTheDocument();
    expect(screen.getByText(t("assets.detail.encrypted_not_set"))).toBeInTheDocument();
  });

  it("reveals an encrypted value only when the API returned it", async () => {
    asset = assetDetail({ encrypted_fields: { secret: "top-secret", owner_email: { is_set: false } } });
    mockAsset();
    renderPage();
    expect(await screen.findByText("top-secret")).toBeInTheDocument();
  });

  it("says so when the asset is not found", async () => {
    server.use(
      http.get("/api/v1/assets/ast-1", () =>
        HttpResponse.json({ code: "asset.not_found", detail: "" }, { status: 404 }),
      ),
    );
    renderPage();
    expect(await screen.findByText(t("assets.detail.not_found_title"))).toBeInTheDocument();
  });

  it("offers Edit and the status menu only to a member who may update", async () => {
    renderPage([READ]);
    await screen.findByRole("heading", { name: "Pump one" });
    expect(screen.queryByRole("button", { name: t("assets.detail.edit") })).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: t("assets.detail.status_actions") })).not.toBeInTheDocument();
  });

  it("uses a select for the tabs on a narrow screen and tabs on a wide one", async () => {
    setViewport(false);
    renderPage();
    const select = await screen.findByLabelText(t("assets.detail.tabs_label"));
    expect(select.tagName).toBe("SELECT");
  });
});

describe("status menu", () => {
  it("lists only the transitions the API returned", async () => {
    renderPage();
    const list = await screen.findByRole("list", { name: t("assets.detail.status_actions") });
    const buttons = within(list).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual([
      t("assets.detail.move_to", { status: "Under repair" }),
      t("assets.detail.move_to", { status: "In storage" }),
    ]);
  });

  it("asks for a reason when one is required, and sends it with the version", async () => {
    server.use(
      http.post("/api/v1/assets/ast-1/change-status", async ({ request }) => {
        statusPosts.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(envelope(assetDetail({ status: "in_repair", version: 5 })));
      }),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Under repair/ }));
    await user.click(screen.getByRole("button", { name: t("assets.detail.confirm_status") }));
    expect(await screen.findByText(t("assets.detail.reason_required"))).toBeInTheDocument();
    expect(statusPosts).toHaveLength(0);

    await user.type(screen.getByLabelText(new RegExp(t("assets.detail.reason_label"))), "Leaking seal");
    await user.click(screen.getByRole("button", { name: t("assets.detail.confirm_status") }));
    await waitFor(() => {
      expect(statusPosts).toEqual([{ to_status: "in_repair", version: 4, reason: "Leaking seal" }]);
    });
    await waitFor(() => {
      expect(screen.getByText("Under repair", { selector: "span" })).toBeInTheDocument();
    });
  });

  it("changes at once when no reason is needed", async () => {
    server.use(
      http.post("/api/v1/assets/ast-1/change-status", async ({ request }) => {
        statusPosts.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(envelope(assetDetail({ status: "in_storage", version: 5 })));
      }),
    );
    renderPage();
    await userEvent.setup().click(await screen.findByRole("button", { name: /In storage/ }));
    await waitFor(() => {
      expect(statusPosts).toEqual([{ to_status: "in_storage", version: 4 }]);
    });
  });

  it("shows the API's message when the change is refused", async () => {
    server.use(
      http.post("/api/v1/assets/ast-1/change-status", () =>
        HttpResponse.json(
          {
            code: "asset.invalid_transition",
            detail: 'Cannot change the status from "in_use" to "in_storage": a holder is still set.',
          },
          { status: 409 },
        ),
      ),
    );
    renderPage();
    await userEvent.setup().click(await screen.findByRole("button", { name: /In storage/ }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/a holder is still set/)).toBeInTheDocument();
  });
});

describe("edit with version handling", () => {
  it("prefills the form, keeps encrypted values blank and sends only what changed", async () => {
    server.use(
      http.patch("/api/v1/assets/ast-1", async ({ request }) => {
        patches.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(envelope(assetDetail({ name: "Pump renamed", version: 5 })));
      }),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: t("assets.detail.edit") }));
    const name = await screen.findByLabelText(new RegExp(`^${t("assets.form.name")}`));
    expect(name).toHaveValue("Pump one");
    expect(await screen.findByLabelText("Hostname")).toHaveValue("pump-01");
    expect(screen.getByLabelText("Secret")).toHaveValue("");
    expect(screen.getByText(t("assets.form.encrypted_set"))).toBeInTheDocument();

    await user.clear(name);
    await user.type(name, "Pump renamed");
    await user.click(screen.getByRole("button", { name: t("assets.form.save_changes") }));
    await waitFor(() => {
      expect(patches).toEqual([{ version: 4, name: "Pump renamed" }]);
    });
    expect(patches[0]).not.toHaveProperty("custom_fields");
    expect(await screen.findByText(t("assets.form.saved"))).toBeInTheDocument();
  });

  it("sends an encrypted field only after something is typed into it", async () => {
    server.use(
      http.patch("/api/v1/assets/ast-1", async ({ request }) => {
        patches.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(envelope(assetDetail({ version: 5 })));
      }),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: t("assets.detail.edit") }));
    await user.type(await screen.findByLabelText("Secret"), "rotated");
    await user.click(screen.getByRole("button", { name: t("assets.form.save_changes") }));
    await waitFor(() => {
      expect(patches).toEqual([{ version: 4, custom_fields: { secret: "rotated" } }]);
    });
  });

  it("offers a reload when the asset changed meanwhile (409), and shows the latest version", async () => {
    server.use(
      http.patch("/api/v1/assets/ast-1", () =>
        HttpResponse.json({ code: "asset.version_conflict", detail: "stale" }, { status: 409 }),
      ),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: t("assets.detail.edit") }));
    const name = await screen.findByLabelText(new RegExp(`^${t("assets.form.name")}`));
    await user.clear(name);
    await user.type(name, "Mine");
    asset = assetDetail({ name: "Theirs", version: 6 });
    mockAsset();
    await user.click(screen.getByRole("button", { name: t("assets.form.save_changes") }));

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(t("assets.detail.conflict_body"))).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: t("assets.detail.conflict_reload") }));
    expect(await screen.findByRole("heading", { name: "Theirs" })).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("asks whether to move components when the owner or location changes", async () => {
    asset = assetDetail({ component_count: 2 });
    mockAsset();
    server.use(
      http.get("/api/v1/locations", () =>
        HttpResponse.json(envelope([{ id: "loc-1", name: "Hall", parent_id: null, path: "hall" }])),
      ),
      http.patch("/api/v1/assets/ast-1", async ({ request }) => {
        patches.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(envelope(assetDetail({ version: 5 })));
      }),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: t("assets.detail.edit") }));
    expect(screen.queryByLabelText(t("assets.form.move_components"))).not.toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Hall" })).toBeInTheDocument();
    });
    await user.selectOptions(screen.getByLabelText(t("assets.form.location")), "loc-1");
    await user.click(screen.getByLabelText(t("assets.form.move_components")));
    await user.click(screen.getByRole("button", { name: t("assets.form.save_changes") }));
    await waitFor(() => {
      expect(patches).toEqual([{ version: 4, location_id: "loc-1", move_components: true }]);
    });
  });
});

describe("components tab", () => {
  const child = {
    component_id: "cmp-1",
    child_asset_id: "ast-2",
    tag: "AST-0002",
    name: "Seal kit",
    status: "in_use",
    attached_at: "2026-09-03T00:00:00Z",
    detached_at: null,
  };

  it("lists components, attaches a found asset and detaches after a confirmation", async () => {
    let components = [child];
    const attached: Record<string, unknown>[] = [];
    const detached: Record<string, unknown>[] = [];
    server.use(
      http.get("/api/v1/assets/ast-1/components", () => HttpResponse.json(envelope({ items: components }))),
      http.get("/api/v1/assets", ({ request }) => {
        const q = new URL(request.url).searchParams.get("q");
        const found = q === "gasket" ? [assetDetail({ id: "ast-3", tag: "AST-0003", name: "Gasket" })] : [];
        return HttpResponse.json(envelope({ items: found, next_cursor: null, total: null }));
      }),
      http.post("/api/v1/assets/ast-1/components", async ({ request }) => {
        attached.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(envelope({}), { status: 201 });
      }),
      http.post("/api/v1/assets/ast-1/components/ast-2/detach", async ({ request }) => {
        detached.push((await request.json()) as Record<string, unknown>);
        components = [];
        return HttpResponse.json(envelope({}));
      }),
    );
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: t("assets.detail.tab_components") }));
    expect(await screen.findByRole("link", { name: "Seal kit" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: t("assets.detail.attach") }));
    await user.type(screen.getByLabelText(t("assets.detail.attach_search")), "gasket");
    await user.click(await screen.findByRole("button", { name: /Gasket/ }));
    await waitFor(() => {
      expect(attached).toEqual([{ child_asset_id: "ast-3", version: 4 }]);
    });

    await user.click(
      await screen.findByRole("button", { name: t("assets.detail.detach_named", { name: "Seal kit" }) }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: t("assets.detail.detach_confirm") }));
    await waitFor(() => {
      expect(detached).toEqual([{ version: 4 }]);
    });
    expect(await screen.findByText(t("assets.detail.no_components"))).toBeInTheDocument();
  });

  it("offers no attach or detach to a member who may not update", async () => {
    server.use(
      http.get("/api/v1/assets/ast-1/components", () => HttpResponse.json(envelope({ items: [child] }))),
    );
    renderPage([READ]);
    await userEvent
      .setup()
      .click(await screen.findByRole("tab", { name: t("assets.detail.tab_components") }));
    await screen.findByRole("link", { name: "Seal kit" });
    expect(screen.queryByRole("button", { name: t("assets.detail.attach") })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Detach/ })).not.toBeInTheDocument();
  });
});
