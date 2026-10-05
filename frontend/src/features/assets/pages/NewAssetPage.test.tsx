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

