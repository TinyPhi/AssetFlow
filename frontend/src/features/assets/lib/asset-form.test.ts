// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { describe, expect, it } from "vitest";
import { ProblemError } from "@/lib/api";
import type { Me } from "@/lib/permissions";
import type { AssetDetail, CustomFieldDefinition, HierarchyNode } from "../types";
import {
  buildCreateBody,
  buildUpdateBody,
  coreErrors,
  coreFromAsset,
  customOutcome,
  EMPTY_CORE,
  hasChanges,
  serverFieldErrors,
  usableOrgUnits,
} from "./asset-form";

function field(key: string, type: string, over: Partial<CustomFieldDefinition> = {}): CustomFieldDefinition {
  return {
    id: key,
    key,
    label: key,
    field_type: type,
    is_encrypted: false,
    status: "active",
    is_required: false,
    is_unique: false,
    position: 0,
    version: 1,
    rules: { min: null, max: null, regex: null, options: [] },
    ...over,
  };
}

function asset(over: Partial<AssetDetail> = {}): AssetDetail {
  return {
    id: "a1",
    tag: "AST-1",
    name: "Pump",
    category_id: "c1",
    category_name: "Pumps",
    model: "M1",
    manufacturer_id: null,
    manufacturer_name: null,
    supplier_id: null,
    supplier_name: null,
    serial_number: null,
    owner_org_unit_id: "ou1",
    owner_org_unit_name: "Plant",
    location_id: "loc1",
    location_name: "Hall",
    holder: null,
    status: "in_use",
    criticality: "high",
    purchase_date: null,
    purchase_cost: "1200.0000",
    warranty_end: null,
    custom_fields: { rpm: 100 },
    encrypted_fields: { secret: { is_set: true } },
    notes: null,
    parent: null,
    component_count: 0,
    version: 3,
    created_at: "",
    updated_at: "",
    ...over,
  };
}

describe("core validation", () => {
  it("needs a category, a name and an owner", () => {
    expect(Object.keys(coreErrors(EMPTY_CORE)).sort()).toEqual(["category_id", "name", "owner_org_unit_id"]);
  });

  it("checks cost and dates", () => {
    const errors = coreErrors({
      ...EMPTY_CORE,
      category_id: "c",
      name: "n",
      owner_org_unit_id: "o",
      purchase_cost: "12,5",
      warranty_end: "soon",
    });
    expect(Object.keys(errors).sort()).toEqual(["purchase_cost", "warranty_end"]);
  });
});

describe("request bodies", () => {
  it("create sends only filled fields, with the typed custom values", () => {
    const body = buildCreateBody(
      { ...EMPTY_CORE, category_id: "c", name: " Pump ", owner_org_unit_id: "o", model: "M" },
      { rpm: 10 },
    );
    expect(body).toEqual({
      name: "Pump",
      category_id: "c",
      owner_org_unit_id: "o",
      model: "M",
      custom_fields: { rpm: 10 },
    });
  });

  it("edit sends changed fields, clear flags and the version", () => {
    const initial = coreFromAsset(asset());
    expect(initial.purchase_cost).toBe("1200");
    const body = buildUpdateBody(
      initial,
      { ...initial, name: "Pump 2", model: "", location_id: "loc2", purchase_cost: "1300.50" },
      {},
      3,
      true,
    );
    expect(body).toEqual({
      version: 3,
      name: "Pump 2",
      clear_model: true,
      location_id: "loc2",
      purchase_cost: "1300.50",
      move_components: true,
    });
  });

  it("edit with no change has nothing to send", () => {
    const initial = coreFromAsset(asset());
    expect(hasChanges(buildUpdateBody(initial, initial, {}, 3, false))).toBe(false);
  });

  it("move_components is left out when neither owner nor location moved", () => {
    const initial = coreFromAsset(asset());
    const body = buildUpdateBody(initial, { ...initial, name: "X" }, {}, 3, true);
    expect(body).not.toHaveProperty("move_components");
  });
});

describe("custom values on edit", () => {
  const defs = [
    field("rpm", "number"),
    field("note", "text"),
    field("secret", "text", { is_encrypted: true }),
  ];

  it("sends only changed plain fields and null for an emptied optional one", () => {
    const outcome = customOutcome(
      defs,
      { rpm: "100", note: "", secret: "" },
      asset({ custom_fields: { rpm: 100, note: "old" } }),
    );
    expect(outcome.errors).toEqual({});
    expect(outcome.data).toEqual({ note: null });
  });

  it("does not send an encrypted field that was not typed into", () => {
    const outcome = customOutcome(defs, { rpm: "100", note: "", secret: "" }, asset());
    expect(outcome.data).not.toHaveProperty("secret");
  });

  it("sends an encrypted field once something is typed", () => {
    const outcome = customOutcome(defs, { rpm: "100", note: "", secret: "s3cret" }, asset());
    expect(outcome.data).toEqual({ secret: "s3cret" });
  });

  it("on create sends every filled field, encrypted ones included", () => {
    const outcome = customOutcome(defs, { rpm: "5", note: "", secret: "x" }, null);
    expect(outcome.data).toEqual({ rpm: 5, secret: "x" });
  });

  it("a required encrypted field that is not set yet must be typed", () => {
    const required = [field("secret", "text", { is_encrypted: true, is_required: true })];
    const none = asset({ encrypted_fields: { secret: { is_set: false } } });
    expect(Object.keys(customOutcome(required, { secret: "" }, none).errors)).toEqual(["secret"]);
    expect(customOutcome(required, { secret: "" }, asset()).errors).toEqual({});
  });
});

describe("org units the member may use", () => {
  const nodes: HierarchyNode[] = [
    { id: "root", parent_id: null, path: "root", name: "Root" },
    { id: "a", parent_id: "root", path: "root.a", name: "A" },
    { id: "a1", parent_id: "a", path: "root.a.a1", name: "A1" },
    { id: "b", parent_id: "root", path: "root.b", name: "B" },
  ];
  const me = (scopes: Me["permissions"][number]["scopes"]): Me => ({
    member_id: "m",
    display_name: "M",
    locale: "en",
    organization: { id: "o", name: "O", timezone: "UTC" },
    is_suspended: false,
    permissions: [{ permission: "asset.create", scopes }],
    installed_modules: [],
  });

  it("all of them with an organization scope", () => {
    expect(
      usableOrgUnits(nodes, me([{ scope_type: "organization", scope_id: null }]), "asset.create"),
    ).toHaveLength(4);
  });

  it("the scoped unit and its descendants only", () => {
    const ids = usableOrgUnits(nodes, me([{ scope_type: "org_unit", scope_id: "a" }]), "asset.create").map(
      (n) => n.id,
    );
    expect(ids).toEqual(["a", "a1"]);
  });

  it("none without the permission", () => {
    expect(
      usableOrgUnits(nodes, me([{ scope_type: "organization", scope_id: null }]), "asset.update"),
    ).toEqual([]);
  });
});

describe("server field errors", () => {
  it("keys the messages by form field and drops a body prefix", () => {
    const error = new ProblemError({
      code: "validation.invalid_field",
      status: 422,
      detail: "",
      errors: [
        { field: "body.name", message: "too long" },
        { field: "custom_fields.rpm", message: "must be a number" },
      ],
    });
    expect(serverFieldErrors(error)).toEqual({ name: "too long", "custom_fields.rpm": "must be a number" });
    expect(serverFieldErrors(new Error("x"))).toEqual({});
  });
});
