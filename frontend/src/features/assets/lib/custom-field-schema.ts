// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// A Zod schema built at run time from a category's custom field definitions (§C4.9): it mirrors the
// server's validation (backend/app/modules/assets/custom_fields.py, P8-04) so a form shows the same
// refusals before it sends; the server still validates again. A form keeps every value as text (or a
// list of texts for a multi-select); the schema turns it into the typed value the API wants.
import { z } from "zod";
import { t } from "@/lib/i18n";
import { isCustomFieldType, type CustomFieldDefinition } from "../types";

export type FieldValue = string | string[];
export type FieldValues = Record<string, FieldValue>;

const MAX_TEXT_LENGTH = 10_000;
const MAX_JSON_BYTES = 16 * 1024;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

type Checked = { ok: true; value: unknown } | { ok: false; message: string };

const ok = (value: unknown): Checked => ({ ok: true, value });
const fail = (message: string): Checked => ({ ok: false, message });

function isEmpty(raw: FieldValue): boolean {
  return typeof raw === "string" ? raw.trim() === "" : raw.length === 0;
}

function checkText(def: CustomFieldDefinition, text: string): Checked {
  if (text.length > MAX_TEXT_LENGTH) return fail(t("assets.form.errors.too_long", { max: MAX_TEXT_LENGTH }));
  const { min, max, regex } = def.rules;
  if (min !== null && text.length < min) return fail(t("assets.form.errors.min_length", { min }));
  if (max !== null && text.length > max) return fail(t("assets.form.errors.max_length", { max }));
  if (regex !== null) {
    let pattern: RegExp | null = null;
    try {
      pattern = new RegExp(`^(?:${regex})$`);
    } catch {
      // A pattern this browser cannot read (the server's flavour differs) is left to the server.
      pattern = null;
    }
    if (pattern !== null && !pattern.test(text)) return fail(t("assets.form.errors.pattern"));
  }
  return ok(text);
}

function checkNumber(def: CustomFieldDefinition, text: string): Checked {
  const value = Number(text);
  if (text === "" || !Number.isFinite(value)) return fail(t("assets.form.errors.number"));
  const { min, max } = def.rules;
  if (min !== null && value < min) return fail(t("assets.form.errors.min_number", { min }));
  if (max !== null && value > max) return fail(t("assets.form.errors.max_number", { max }));
  return ok(value);
}

function checkDate(text: string): Checked {
  const parsed = new Date(`${text}T00:00:00Z`);
  if (!DATE_RE.test(text) || Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== text) {
    return fail(t("assets.form.errors.date"));
  }
  return ok(text);
}

function checkJson(text: string): Checked {
  if (new TextEncoder().encode(text).length > MAX_JSON_BYTES) {
    return fail(t("assets.form.errors.json_too_large"));
  }
  try {
    return ok(JSON.parse(text) as unknown);
  } catch {
    return fail(t("assets.form.errors.json"));
  }
}

/** One value against its definition: an empty optional value is "no value" (`undefined`), never an error. */
export function checkFieldValue(def: CustomFieldDefinition, raw: FieldValue): Checked {
  if (isEmpty(raw)) return def.is_required ? fail(t("assets.form.errors.required")) : ok(undefined);
  const type = isCustomFieldType(def.field_type) ? def.field_type : "text";
  if (type === "multi_select") {
    const picked = typeof raw === "string" ? [raw] : raw;
    const unknown = picked.find((option) => !def.rules.options.includes(option));
    return unknown === undefined ? ok(picked) : fail(t("assets.form.errors.option"));
  }
  const text = (typeof raw === "string" ? raw : (raw[0] ?? "")).trim();
  switch (type) {
    case "text":
      return checkText(def, text);
    case "number":
      return checkNumber(def, text);
    case "date":
      return checkDate(text);
    case "boolean":
      return text === "true" || text === "false" ? ok(text === "true") : fail(t("assets.form.errors.option"));
    case "select":
      return def.rules.options.includes(text) ? ok(text) : fail(t("assets.form.errors.option"));
    case "json":
      return checkJson(text);
  }
}

/** The schema of one field. */
export function buildFieldSchema(def: CustomFieldDefinition): z.ZodType<unknown, z.ZodTypeDef, FieldValue> {
  return z.union([z.string(), z.array(z.string())]).transform((raw, ctx) => {
    const checked = checkFieldValue(def, raw);
    if (checked.ok) return checked.value;
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: checked.message });
    return z.NEVER;
  });
}

/** The schema of a whole form's custom fields, one key per definition. */
export function buildCustomFieldsSchema(defs: readonly CustomFieldDefinition[]) {
  const shape: Record<string, z.ZodType<unknown, z.ZodTypeDef, FieldValue>> = {};
  for (const def of defs) shape[def.key] = buildFieldSchema(def);
  return z.object(shape);
}

export type CustomFieldsResult =
  { ok: true; data: Record<string, unknown> } | { ok: false; errors: Record<string, string> };

/**
 * Validate `values` against `defs`: typed data keyed by field key (an empty optional field is left out), or
 * one message per failing key. A key with no value in `values` counts as empty.
 */
export function parseCustomFieldValues(
  defs: readonly CustomFieldDefinition[],
  values: Readonly<FieldValues>,
): CustomFieldsResult {
  const input: FieldValues = {};
  for (const def of defs) input[def.key] = values[def.key] ?? "";
  const result = buildCustomFieldsSchema(defs).safeParse(input);
  if (result.success) {
    const data: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(result.data)) {
      if (value !== undefined) data[key] = value;
    }
    return { ok: true, data };
  }
  const errors: Record<string, string> = {};
  for (const issue of result.error.issues) {
    const key = issue.path[0];
    if (typeof key === "string" && errors[key] === undefined) errors[key] = issue.message;
  }
  return { ok: false, errors };
}

/** A stored value as the text a form shows. */
export function toFieldValue(def: CustomFieldDefinition, stored: unknown): FieldValue {
  if (def.field_type === "multi_select") {
    return Array.isArray(stored) ? (stored as unknown[]).map(String) : [];
  }
  if (stored === null || stored === undefined) return "";
  if (def.field_type === "json") return JSON.stringify(stored, null, 2);
  if (typeof stored === "string") return stored;
  if (typeof stored === "number" || typeof stored === "boolean") return String(stored);
  return JSON.stringify(stored);
}
