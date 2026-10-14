// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// The catalog administration forms' state, checks and request bodies (mirrors backend/app/modules/assets/
// catalog/schemas.py). Every value is text until submit.
import { ProblemError } from "@/lib/api";
import { t } from "@/lib/i18n";
import type {
  CategoryCreateInput,
  CategoryUpdateInput,
  FieldCreateInput,
  FieldUpdateInput,
} from "../api/catalog";
import type { CategoryRecord, CustomFieldDefinition, HierarchyNode } from "../types";

const KEY_RE = /^[a-z][a-z0-9_]*$/;
const CODE_RE = /^[a-z0-9_]+(-[a-z0-9_]+)*$/i;
const PREFIX_RE = /^[A-Z][A-Z0-9]{0,9}$/;
const MAX_REGEX = 200;

export type Errors = Record<string, string>;

const required = (): string => t("assets.form.errors.required");

// ---- categories ----------------------------------------------------------------------------------------------

export interface CategoryFormValues {
  code: string;
  name: string;
  parent_id: string;
  tag_prefix: string;
  default_criticality: string;
}

export const EMPTY_CATEGORY: CategoryFormValues = {
  code: "",
  name: "",
  parent_id: "",
  tag_prefix: "",
  default_criticality: "",
};

export function categoryValues(category: CategoryRecord): CategoryFormValues {
  return {
    code: category.code,
    name: category.name,
    parent_id: category.parent_id ?? "",
    tag_prefix: category.tag_prefix ?? "",
    default_criticality: category.default_criticality ?? "",
  };
}

export function categoryErrors(values: CategoryFormValues, mode: "create" | "edit"): Errors {
  const errors: Errors = {};
  if (mode === "create") {
    if (values.code.trim() === "") errors["code"] = required();
    else if (!CODE_RE.test(values.code.trim()) || values.code.trim().length > 64) {
      errors["code"] = t("assets.categories.errors.code");
    }
  }
  if (values.name.trim() === "") errors["name"] = required();
  if (values.tag_prefix.trim() !== "" && !PREFIX_RE.test(values.tag_prefix.trim())) {
    errors["tag_prefix"] = t("assets.categories.errors.tag_prefix");
  }
  return errors;
}

export function categoryCreateBody(values: CategoryFormValues): CategoryCreateInput {
  return {
    code: values.code.trim(),
    name: values.name.trim(),
    ...(values.parent_id === "" ? {} : { parent_id: values.parent_id }),
    ...(values.tag_prefix.trim() === "" ? {} : { tag_prefix: values.tag_prefix.trim() }),
    ...(values.default_criticality === "" ? {} : { default_criticality: values.default_criticality }),
  };
}

/** Only what changed; an emptied prefix or default is cleared with its `clear_*` flag. */
export function categoryUpdateBody(
  initial: CategoryFormValues,
  values: CategoryFormValues,
  version: number,
): CategoryUpdateInput {
  const body: CategoryUpdateInput = { version };
  if (values.name.trim() !== initial.name) body["name"] = values.name.trim();
  const prefix = values.tag_prefix.trim();
  if (prefix !== initial.tag_prefix) {
    if (prefix === "") body["clear_tag_prefix"] = true;
    else body["tag_prefix"] = prefix;
  }
  if (values.default_criticality !== initial.default_criticality) {
    if (values.default_criticality === "") body["clear_default_criticality"] = true;
    else body["default_criticality"] = values.default_criticality;
  }
  return body;
}

/** The categories a category may be moved under: not itself and not one of its own descendants. */
export function moveTargets(nodes: readonly CategoryRecord[], moving: HierarchyNode): CategoryRecord[] {
  return nodes.filter(
    (node) =>
      node.id !== moving.id &&
      node.status === "active" &&
      !(moving.path !== "" && node.path.startsWith(`${moving.path}.`)),
  );
}

// ---- custom field definitions --------------------------------------------------------------------------------

export interface FieldFormValues {
  key: string;
  label: string;
  field_type: string;
  is_required: boolean;
  is_unique: boolean;
  is_encrypted: boolean;
  min: string;
  max: string;
  regex: string;
  optionsText: string;
  position: string;
}

export const EMPTY_FIELD: FieldFormValues = {
  key: "",
  label: "",
  field_type: "text",
  is_required: false,
  is_unique: false,
  is_encrypted: false,
  min: "",
  max: "",
  regex: "",
  optionsText: "",
  position: "0",
};

export function fieldValues(def: CustomFieldDefinition): FieldFormValues {
  return {
    key: def.key,
    label: def.label,
    field_type: def.field_type,
    is_required: def.is_required,
    is_unique: def.is_unique,
    is_encrypted: def.is_encrypted,
    min: def.rules.min === null ? "" : String(def.rules.min),
    max: def.rules.max === null ? "" : String(def.rules.max),
    regex: def.rules.regex ?? "",
    optionsText: def.rules.options.join("\n"),
    position: String(def.position),
  };
}

export function optionsFromText(text: string): string[] {
  const seen = new Set<string>();
  for (const line of text.split("\n")) {
    const option = line.trim();
    if (option !== "") seen.add(option);
  }
  return [...seen];
}

const usesBounds = (type: string): boolean => type === "text" || type === "number";
const usesOptions = (type: string): boolean => type === "select" || type === "multi_select";

export function fieldErrors(values: FieldFormValues, mode: "create" | "edit"): Errors {
  const errors: Errors = {};
  if (mode === "create" && !KEY_RE.test(values.key)) errors["key"] = t("assets.categories.errors.key");
  if (values.label.trim() === "") errors["label"] = required();
  if (usesOptions(values.field_type) && optionsFromText(values.optionsText).length === 0) {
    errors["optionsText"] = t("assets.categories.errors.options");
  }
  const min = values.min.trim() === "" ? null : Number(values.min);
  const max = values.max.trim() === "" ? null : Number(values.max);
  if (usesBounds(values.field_type)) {
    if (min !== null && !Number.isFinite(min)) errors["min"] = t("assets.form.errors.number");
    if (max !== null && !Number.isFinite(max)) errors["max"] = t("assets.form.errors.number");
    if (min !== null && max !== null && Number.isFinite(min) && Number.isFinite(max) && min > max) {
      errors["max"] = t("assets.categories.errors.range");
    }
  }
  if (values.field_type === "text" && values.regex !== "") {
    if (values.regex.length > MAX_REGEX)
      errors["regex"] = t("assets.form.errors.too_long", { max: MAX_REGEX });
    else {
      try {
        new RegExp(values.regex);
      } catch {
        errors["regex"] = t("assets.categories.errors.regex");
      }
    }
  }
  if (!/^-?\d+$/.test(values.position.trim())) errors["position"] = t("assets.form.errors.number");
  if (values.is_unique && values.is_encrypted)
    errors["is_unique"] = t("assets.categories.errors.unique_encrypted");
  return errors;
}

export function fieldCreateBody(values: FieldFormValues): FieldCreateInput {
  const body: FieldCreateInput = {
    key: values.key,
    label: values.label.trim(),
    field_type: values.field_type,
    is_required: values.is_required,
    is_unique: values.is_unique,
    is_encrypted: values.is_encrypted,
    position: Number(values.position),
  };
  if (usesBounds(values.field_type)) {
    if (values.min.trim() !== "") body.min = Number(values.min);
    if (values.max.trim() !== "") body.max = Number(values.max);
  }
  if (values.field_type === "text" && values.regex !== "") body.regex = values.regex;
  if (usesOptions(values.field_type)) body.options = optionsFromText(values.optionsText);
  return body;
}

/** Only what changed; an emptied bound or pattern is cleared with its `clear_*` flag. The key and the
 * encrypted flag are fixed after creation. */
export function fieldUpdateBody(
  initial: FieldFormValues,
  values: FieldFormValues,
  version: number,
): FieldUpdateInput {
  const body: FieldUpdateInput = { version };
  if (values.label.trim() !== initial.label) body["label"] = values.label.trim();
  if (values.field_type !== initial.field_type) body["field_type"] = values.field_type;
  if (values.is_required !== initial.is_required) body["is_required"] = values.is_required;
  if (values.is_unique !== initial.is_unique) body["is_unique"] = values.is_unique;
  if (values.position.trim() !== initial.position.trim()) body["position"] = Number(values.position);
  for (const key of ["min", "max"] as const) {
    if (!usesBounds(values.field_type) || values[key].trim() === initial[key].trim()) continue;
    if (values[key].trim() === "") body[`clear_${key}`] = true;
    else body[key] = Number(values[key]);
  }
  if (values.field_type === "text" && values.regex !== initial.regex) {
    if (values.regex === "") body["clear_regex"] = true;
    else body["regex"] = values.regex;
  }
  if (usesOptions(values.field_type) && values.optionsText !== initial.optionsText) {
    body["options"] = optionsFromText(values.optionsText);
  }
  return body;
}

// ---- manufacturers and suppliers -------------------------------------------------------------------------------

export interface PartyFormValues {
  code: string;
  name: string;
  notes: string;
}

export const EMPTY_PARTY: PartyFormValues = { code: "", name: "", notes: "" };

export function partyErrors(values: PartyFormValues, mode: "create" | "edit"): Errors {
  const errors: Errors = {};
  if (values.name.trim() === "") errors["name"] = required();
  if (mode === "create" && values.code.trim() !== "" && !CODE_RE.test(values.code.trim())) {
    errors["code"] = t("assets.categories.errors.code");
  }
  return errors;
}

// ---- failures ------------------------------------------------------------------------------------------------------

/** A refused catalog write in words: a version conflict, a blocker the API explains, or a generic failure. */
export function catalogFailure(error: unknown): string {
  if (error instanceof ProblemError) {
    if (error.code.endsWith(".version_conflict")) return t("assets.categories.conflict");
    if (error.status === 403) return t("assets.form.denied");
    if (error.detail !== "") return error.detail;
  }
  return t("assets.categories.save_failed");
}
