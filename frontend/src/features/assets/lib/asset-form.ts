// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// The asset form's state, validation and request bodies. The form keeps every value as text; this turns
// it into the API's create body or a minimal edit body (changed fields only, `clear_*` flags, `version`).
import { z } from "zod";
import { ProblemError } from "@/lib/api";
import { t } from "@/lib/i18n";
import { can, type Me } from "@/lib/permissions";
import type { AssetDetail, CustomFieldDefinition, HierarchyNode } from "../types";
import {
  parseCustomFieldValues,
  toFieldValue,
  type FieldValue,
  type FieldValues,
} from "./custom-field-schema";

export interface CoreValues {
  category_id: string;
  name: string;
  model: string;
  manufacturer_id: string;
  supplier_id: string;
  serial_number: string;
  owner_org_unit_id: string;
  location_id: string;
  criticality: string;
  purchase_date: string;
  purchase_cost: string;
  warranty_end: string;
  notes: string;
}

export const EMPTY_CORE: CoreValues = {
  category_id: "",
  name: "",
  model: "",
  manufacturer_id: "",
  supplier_id: "",
  serial_number: "",
  owner_org_unit_id: "",
  location_id: "",
  criticality: "",
  purchase_date: "",
  purchase_cost: "",
  warranty_end: "",
  notes: "",
};

const MAX_NAME = 255;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const COST_RE = /^\d+(\.\d{1,2})?$/;

const optionalText = z
  .string()
  .max(MAX_NAME, { message: t("assets.form.errors.too_long", { max: MAX_NAME }) });
const optionalDate = z
  .string()
  .refine((value) => value === "" || DATE_RE.test(value), { message: t("assets.form.errors.date") });

/** The core fields' schema (mirrors `AssetCreate`/`AssetUpdate` in backend/app/modules/assets/schemas.py). */
export function coreSchema() {
  return z.object({
    category_id: z.string().min(1, { message: t("assets.form.errors.required") }),
    name: z
      .string()
      .trim()
      .min(1, { message: t("assets.form.errors.required") })
      .max(MAX_NAME, { message: t("assets.form.errors.too_long", { max: MAX_NAME }) }),
    model: optionalText,
    manufacturer_id: z.string(),
    supplier_id: z.string(),
    serial_number: optionalText,
    owner_org_unit_id: z.string().min(1, { message: t("assets.form.errors.required") }),
    location_id: z.string(),
    criticality: z.string(),
    purchase_date: optionalDate,
    purchase_cost: z.string().refine((value) => value === "" || COST_RE.test(value.trim()), {
      message: t("assets.form.errors.cost"),
    }),
    warranty_end: optionalDate,
    notes: z.string(),
  });
}

export function coreErrors(values: CoreValues): Record<string, string> {
  const result = coreSchema().safeParse(values);
  const errors: Record<string, string> = {};
  if (!result.success) {
    for (const issue of result.error.issues) {
      const key = issue.path[0];
      if (typeof key === "string" && errors[key] === undefined) errors[key] = issue.message;
    }
  }
  return errors;
}

export function coreFromAsset(asset: AssetDetail): CoreValues {
  return {
    category_id: asset.category_id,
    name: asset.name,
    model: asset.model ?? "",
    manufacturer_id: asset.manufacturer_id ?? "",
    supplier_id: asset.supplier_id ?? "",
    serial_number: asset.serial_number ?? "",
    owner_org_unit_id: asset.owner_org_unit_id,
    location_id: asset.location_id ?? "",
    criticality: asset.criticality ?? "",
    purchase_date: asset.purchase_date ?? "",
    purchase_cost: asset.purchase_cost === null ? "" : trimCost(asset.purchase_cost),
    warranty_end: asset.warranty_end ?? "",
    notes: asset.notes ?? "",
  };
}

/** `"1200.0000"` becomes `"1200"`; a value with real decimals keeps them. */
function trimCost(cost: string): string {
  return cost.includes(".") ? cost.replace(/\.?0+$/, "") : cost;
}

/** The values of the category's custom fields as an edit form starts with them. */
export function customValuesFromAsset(
  defs: readonly CustomFieldDefinition[],
  asset: AssetDetail,
): FieldValues {
  const values: FieldValues = {};
  for (const def of defs) {
    if (def.is_encrypted) {
      // An encrypted value is never prefilled: the form shows "set / not set" and sends only what is typed.
      values[def.key] = "";
      continue;
    }
    values[def.key] = toFieldValue(def, asset.custom_fields[def.key]);
  }
  return values;
}

/** Whether the asset has a stored value for this encrypted field (or the caller may see the value). */
export function encryptedIsSet(asset: AssetDetail | null, key: string): boolean {
  const entry = asset?.encrypted_fields[key];
  if (entry === undefined) return false;
  return "is_set" in entry ? entry.is_set : true;
}

function sameValue(a: FieldValue, b: FieldValue): boolean {
  if (typeof a === "string" && typeof b === "string") return a.trim() === b.trim();
  return JSON.stringify(a) === JSON.stringify(b);
}

export interface CustomOutcome {
  /** Typed values to send, keyed by field key. */
  data: Record<string, unknown>;
  errors: Record<string, string>;
}

/**
 * Validate the custom fields. Create: every definition. Edit: a plain field is checked always and sent only
 * when changed (an emptied optional field is sent as null); an encrypted field is checked and sent only when
 * something was typed (a required one that is not set yet must be typed).
 */
export function customOutcome(
  defs: readonly CustomFieldDefinition[],
  values: Readonly<FieldValues>,
  asset: AssetDetail | null,
): CustomOutcome {
  const initial = asset === null ? {} : customValuesFromAsset(defs, asset);
  const checked = defs.filter((def) => {
    if (!def.is_encrypted) return true;
    const typed = values[def.key];
    const hasTyped = typed !== undefined && typed !== "" && !(Array.isArray(typed) && typed.length === 0);
    return (
      hasTyped || (asset === null ? def.is_required : def.is_required && !encryptedIsSet(asset, def.key))
    );
  });
  const result = parseCustomFieldValues(checked, values);
  if (!result.ok) return { data: {}, errors: result.errors };
  if (asset === null) return { data: result.data, errors: {} };
  const data: Record<string, unknown> = {};
  for (const def of checked) {
    const now = values[def.key] ?? "";
    if (def.is_encrypted) {
      if (def.key in result.data) data[def.key] = result.data[def.key];
      continue;
    }
    if (sameValue(now, initial[def.key] ?? "")) continue;
    data[def.key] = def.key in result.data ? result.data[def.key] : null;
  }
  return { data, errors: {} };
}

function blankToUndefined(value: string): string | undefined {
  return value.trim() === "" ? undefined : value.trim();
}

export function buildCreateBody(core: CoreValues, custom: Record<string, unknown>): Record<string, unknown> {
  const body: Record<string, unknown> = {
    name: core.name.trim(),
    category_id: core.category_id,
    owner_org_unit_id: core.owner_org_unit_id,
    custom_fields: custom,
  };
  const optional: [string, string][] = [
    ["model", core.model],
    ["manufacturer_id", core.manufacturer_id],
    ["supplier_id", core.supplier_id],
    ["serial_number", core.serial_number],
    ["location_id", core.location_id],
    ["criticality", core.criticality],
    ["purchase_date", core.purchase_date],
    ["purchase_cost", core.purchase_cost],
    ["warranty_end", core.warranty_end],
    ["notes", core.notes],
  ];
  for (const [key, value] of optional) {
    const text = blankToUndefined(value);
    if (text !== undefined) body[key] = text;
  }
  return body;
}

/** The members of an edit that the API takes as a value plus a `clear_*` flag. */
const CLEARABLE: readonly (keyof CoreValues)[] = [
  "model",
  "manufacturer_id",
  "supplier_id",
  "serial_number",
  "location_id",
  "purchase_date",
  "purchase_cost",
  "warranty_end",
  "notes",
];

const CLEAR_FLAG: Record<string, string> = {
  model: "clear_model",
  manufacturer_id: "clear_manufacturer",
  supplier_id: "clear_supplier",
  serial_number: "clear_serial_number",
  location_id: "clear_location",
  purchase_date: "clear_purchase_date",
  purchase_cost: "clear_purchase_cost",
  warranty_end: "clear_warranty_end",
  notes: "clear_notes",
};

/** An edit body with only what changed; `moveComponents` is sent only when a location or owner moved. */
export function buildUpdateBody(
  initial: CoreValues,
  core: CoreValues,
  custom: Record<string, unknown>,
  version: number,
  moveComponents: boolean,
): Record<string, unknown> & { version: number } {
  const body: Record<string, unknown> & { version: number } = { version };
  if (core.name.trim() !== initial.name) body["name"] = core.name.trim();
  if (core.owner_org_unit_id !== initial.owner_org_unit_id) {
    body["owner_org_unit_id"] = core.owner_org_unit_id;
  }
  if (core.criticality !== initial.criticality && core.criticality !== "") {
    body["criticality"] = core.criticality;
  }
  for (const key of CLEARABLE) {
    const now = core[key].trim();
    if (now === initial[key].trim()) continue;
    const flag = CLEAR_FLAG[key];
    if (now === "" && flag !== undefined) body[flag] = true;
    else body[key] = now;
  }
  if (Object.keys(custom).length > 0) body["custom_fields"] = custom;
  if (moveComponents && ownerOrLocationChanged(initial, core)) body["move_components"] = true;
  return body;
}

export function ownerOrLocationChanged(initial: CoreValues, core: CoreValues): boolean {
  return core.owner_org_unit_id !== initial.owner_org_unit_id || core.location_id !== initial.location_id;
}

/** Whether an edit changes anything at all (so "Save" with no change is not sent). */
export function hasChanges(body: Record<string, unknown>): boolean {
  return Object.keys(body).some((key) => key !== "version");
}

/**
 * The org units `me` may use for `permission` (create or update): all of them with an organization scope,
 * otherwise each unit scope's unit and its descendants (by path). The API still decides.
 */
export function usableOrgUnits(
  nodes: readonly HierarchyNode[],
  me: Me | undefined,
  permission: string,
): HierarchyNode[] {
  const granted = me?.permissions.find((p) => p.permission === permission);
  if (me === undefined || granted === undefined || !can(me, permission)) return [];
  if (granted.scopes.some((scope) => scope.scope_type === "organization")) return [...nodes];
  const roots = granted.scopes.flatMap((scope) =>
    scope.scope_type === "org_unit" ? nodes.filter((node) => node.id === scope.scope_id) : [],
  );
  return nodes.filter((node) =>
    roots.some((root) => node.id === root.id || (root.path !== "" && node.path.startsWith(`${root.path}.`))),
  );
}

/** Field errors from a 422, keyed by the form's own names (`custom_fields.<key>` stays as it is). */
export function serverFieldErrors(error: unknown): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!(error instanceof ProblemError)) return errors;
  for (const item of error.errors) {
    const field = item.field.replace(/^(body|query)\./, "");
    if (errors[field] === undefined) errors[field] = item.message;
  }
  return errors;
}
