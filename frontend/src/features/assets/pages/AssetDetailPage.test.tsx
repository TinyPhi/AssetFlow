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

