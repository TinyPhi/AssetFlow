// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { t } from "@/lib/i18n";
import { envelope, server } from "@/test/server";
import { assetDetail, fieldDef, grant, mockLookups, renderAt } from "../test-support";
import { NewAssetPage } from "./NewAssetPage";

const FIELDS = [
  fieldDef("hostname", "text", { is_required: true, rules: { regex: "[a-z]+" } }),
  fieldDef("power", "number", { rules: { min: 0, max: 100 } }),
  fieldDef("secret", "text", { is_encrypted: true }),
];

let posted: { body: Record<string, unknown>; key: string | null }[] = [];

function mockCreate(respond?: () => Response): void {
  server.use(
    http.post("/api/v1/assets", async ({ request }) => {
      posted.push({
        body: (await request.json()) as Record<string, unknown>,
        key: request.headers.get("Idempotency-Key"),
      });
      if (respond !== undefined) return respond();
      return HttpResponse.json(envelope(assetDetail({ id: "new-1", tag: "AST-0042" })), { status: 201 });
    }),
  );
}

async function fillCore(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await screen.findByRole("option", { name: "Pumps" });
  await user.selectOptions(screen.getByLabelText(new RegExp(t("assets.form.category"))), "cat-1");
  await user.type(screen.getByLabelText(new RegExp(`^${t("assets.form.name")}`)), "Pump two");
  await screen.findByRole("option", { name: "Plant A" });
  await user.selectOptions(screen.getByLabelText(new RegExp(t("assets.form.owner_org_unit"))), "ou-1");
}

function renderPage(): void {
  renderAt(<NewAssetPage />, "/assets/new", "/assets/new", [grant("asset.create")]);
}

beforeEach(() => {
  posted = [];
  mockLookups(FIELDS);
});

describe("NewAssetPage", () => {
  it("creates an asset with typed custom fields, sends the encrypted one, and opens the new asset", async () => {
    mockCreate();
    renderPage();
    const user = userEvent.setup();
    await fillCore(user);

    // Choosing the category defaults the criticality and shows its fields.
    expect(await screen.findByLabelText(new RegExp(`^${t("assets.form.criticality")}`))).toHaveValue("high");
    await user.type(await screen.findByLabelText(/^Hostname/), "pump");
    await user.type(screen.getByLabelText("Power"), "42.5");
    const secret = screen.getByLabelText("Secret");
    expect(secret).toHaveAttribute("type", "password");
    await user.type(secret, "s3cret");
    await user.click(screen.getByRole("button", { name: t("assets.form.create") }));

    await waitFor(() => {
      expect(posted).toHaveLength(1);
    });
    expect(posted[0]?.body).toEqual({
      name: "Pump two",
      category_id: "cat-1",
      owner_org_unit_id: "ou-1",
      criticality: "high",
      custom_fields: { hostname: "pump", power: 42.5, secret: "s3cret" },
    });
    expect(posted[0]?.key).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByTestId("path")).toHaveTextContent("/assets/new-1");
    });
  });

  it("shows the generated tag in a toast", async () => {
    mockCreate();
    renderPage();
    const user = userEvent.setup();
    await fillCore(user);
    await user.type(await screen.findByLabelText(/^Hostname/), "pump");
    await user.click(screen.getByRole("button", { name: t("assets.form.create") }));
    expect(await screen.findByText(t("assets.form.created", { tag: "AST-0042" }))).toBeInTheDocument();
  });

  it("checks the form before sending: required fields and field rules", async () => {
    mockCreate();
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: t("assets.form.create") }));
    expect((await screen.findAllByText(t("assets.form.errors.required"))).length).toBeGreaterThanOrEqual(3);

    await fillCore(user);
    await user.type(await screen.findByLabelText(/^Hostname/), "BAD1");
    await user.type(screen.getByLabelText("Power"), "500");
    await user.click(screen.getByRole("button", { name: t("assets.form.create") }));
    expect(await screen.findByText(t("assets.form.errors.pattern"))).toBeInTheDocument();
    expect(screen.getByText(t("assets.form.errors.max_number", { max: 100 }))).toBeInTheDocument();
    expect(posted).toHaveLength(0);
  });

  it("maps server 422 field errors back onto the inputs and keeps what was typed", async () => {
    mockCreate(() =>
      HttpResponse.json(
        {
          code: "asset.custom_field_invalid",
          status: 422,
          detail: "invalid",
          errors: [
            { field: "custom_fields.hostname", message: "hostname already used" },
            { field: "body.name", message: "name is taken" },
          ],
        },
        { status: 422, headers: { "Content-Type": "application/problem+json" } },
      ),
    );
    renderPage();
    const user = userEvent.setup();
    await fillCore(user);
    await user.type(await screen.findByLabelText(/^Hostname/), "pump");
    await user.click(screen.getByRole("button", { name: t("assets.form.create") }));

    const hostname = await screen.findByLabelText(/^Hostname/);
    await waitFor(() => {
      expect(hostname).toHaveAccessibleDescription("hostname already used");
    });
    expect(screen.getByLabelText(new RegExp(`^${t("assets.form.name")}`))).toHaveAccessibleDescription(
      "name is taken",
    );
    expect(screen.getByText(t("assets.form.fix_errors"))).toBeInTheDocument();
    expect(hostname).toHaveValue("pump");
  });

  it("limits the owner org unit to units the member may create in", async () => {
    server.use(
      http.get("/api/v1/org-units", () =>
        HttpResponse.json(
          envelope([
            { id: "ou-1", name: "Plant A", parent_id: null, path: "a" },
            { id: "ou-2", name: "Plant B", parent_id: null, path: "b" },
          ]),
        ),
      ),
    );
    renderAt(<NewAssetPage />, "/assets/new", "/assets/new", [
      { permission: "asset.create", scopes: [{ scope_type: "org_unit", scope_id: "ou-2" }] },
    ]);
    const select = await screen.findByLabelText(new RegExp(t("assets.form.owner_org_unit")));
    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Plant B" })).toBeInTheDocument();
    });
    expect(select).not.toHaveTextContent("Plant A");
  });
});
