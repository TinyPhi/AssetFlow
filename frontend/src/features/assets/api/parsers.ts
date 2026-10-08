// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Narrowing of unknown API JSON into the asset list's types: no cast trusts the wire. A malformed
// item is dropped rather than shown half-filled; a malformed envelope throws, and the list's error
// state shows it.
import { ProblemError } from "@/lib/api";
import type {
  AssetHolder,
  AssetListItem,
  AssetPage,
  CustomFieldDefinition,
  CustomFieldRules,
  HierarchyNode,
  HolderType,
  SavedView,
  SavedViewQuery,
  TeamOption,
} from "../types";

export type Rec = Record<string, unknown>;

export function isRec(value: unknown): value is Rec {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function strOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function invalid(): ProblemError {
  return new ProblemError({ code: "invalid_response", status: 200, detail: "" });
}

function holderType(value: unknown): HolderType | null {
  return value === "member" || value === "team" || value === "location" ? value : null;
}

function parseHolder(value: unknown): AssetHolder | null {
  if (!isRec(value)) return null;
  const type = holderType(value["type"]);
  const id = str(value["id"]);
  const name = str(value["display_name"]);
  return type !== null && id !== null && name !== null ? { type, id, display_name: name } : null;
}

export function parseAssetItem(value: unknown): AssetListItem | null {
  if (!isRec(value)) return null;
  const id = str(value["id"]);
  const tag = str(value["tag"]);
  const name = str(value["name"]);
  const status = str(value["status"]);
  const categoryId = str(value["category_id"]);
  const ownerId = str(value["owner_org_unit_id"]);
  if (id === null || tag === null || name === null || status === null) return null;
  if (categoryId === null || ownerId === null) return null;
  return {
    id,
    tag,
    name,
    category_id: categoryId,
    category_name: str(value["category_name"]) ?? "",
    model: strOrNull(value["model"]),
    manufacturer_name: strOrNull(value["manufacturer_name"]),
    serial_number: strOrNull(value["serial_number"]),
    owner_org_unit_id: ownerId,
    owner_org_unit_name: str(value["owner_org_unit_name"]) ?? "",
    location_id: strOrNull(value["location_id"]),
    location_name: strOrNull(value["location_name"]),
    holder: parseHolder(value["holder"]),
    status,
    criticality: strOrNull(value["criticality"]),
    warranty_end: strOrNull(value["warranty_end"]),
    purchase_date: strOrNull(value["purchase_date"]),
    version: typeof value["version"] === "number" ? value["version"] : 1,
    created_at: str(value["created_at"]) ?? "",
    updated_at: str(value["updated_at"]) ?? "",
  };
}

export function items<T>(value: unknown, parse: (item: unknown) => T | null): T[] {
  if (!Array.isArray(value)) throw invalid();
  return (value as unknown[]).map(parse).filter((item): item is T => item !== null);
}

export function parseAssetPage(value: unknown): AssetPage {
  if (!isRec(value)) throw invalid();
  return {
    items: items(value["items"], parseAssetItem),
    next_cursor: strOrNull(value["next_cursor"]),
    total: typeof value["total"] === "number" ? value["total"] : null,
  };
}

function parseQuery(value: unknown): SavedViewQuery {
  const query: SavedViewQuery = {};
  if (!isRec(value)) return query;
  const scalar = (v: unknown): v is string | number | boolean =>
    typeof v === "string" || typeof v === "number" || typeof v === "boolean";
  for (const [key, v] of Object.entries(value)) {
    if (scalar(v)) query[key] = v;
    else if (Array.isArray(v) && (v as unknown[]).every(scalar))
      query[key] = v as (string | number | boolean)[];
  }
  return query;
}

export function parseSavedView(value: unknown): SavedView | null {
  if (!isRec(value)) return null;
  const id = str(value["id"]);
  const name = str(value["name"]);
  if (id === null || name === null) return null;
  const columns = Array.isArray(value["columns"])
    ? (value["columns"] as unknown[]).filter((c): c is string => typeof c === "string")
    : [];
  return {
    id,
    name,
    query: parseQuery(value["query"]),
    sort: str(value["sort"]) ?? "-created_at",
    columns,
    version: typeof value["version"] === "number" ? value["version"] : 1,
  };
}

export function parseSavedViews(value: unknown): SavedView[] {
  if (!isRec(value)) throw invalid();
  return items(value["items"], parseSavedView);
}

export function parseHierarchyNode(value: unknown): HierarchyNode | null {
  if (!isRec(value)) return null;
  const id = str(value["id"]);
  const name = str(value["name"]);
  if (id === null || name === null) return null;
  return { id, name, parent_id: strOrNull(value["parent_id"]), path: str(value["path"]) ?? "" };
}

/** A hierarchy list as a bare array (org units, locations) or as a cursor page (categories). */
export function parseHierarchyList(value: unknown): { nodes: HierarchyNode[]; next: string | null } {
  if (Array.isArray(value)) return { nodes: items(value, parseHierarchyNode), next: null };
  if (isRec(value))
    return { nodes: items(value["items"], parseHierarchyNode), next: strOrNull(value["next_cursor"]) };
  throw invalid();
}

export function parseTeams(value: unknown): TeamOption[] {
  const parse = (item: unknown): TeamOption | null => {
    if (!isRec(item)) return null;
    const id = str(item["id"]);
    const name = str(item["name"]);
    return id !== null && name !== null ? { id, name } : null;
  };
  return items(value, parse);
}

function num(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

function parseRules(value: unknown): CustomFieldRules {
  const rec: Rec = isRec(value) ? value : {};
  const options = Array.isArray(rec["options"])
    ? (rec["options"] as unknown[]).filter((o): o is string => typeof o === "string")
    : [];
  return { min: num(rec["min"]), max: num(rec["max"]), regex: strOrNull(rec["regex"]), options };
}

export function parseCustomField(item: unknown): CustomFieldDefinition | null {
  if (!isRec(item)) return null;
  const id = str(item["id"]);
  const key = str(item["key"]);
  const label = str(item["label"]);
  const type = str(item["field_type"]);
  if (id === null || key === null || label === null || type === null) return null;
  return {
    id,
    key,
    label,
    field_type: type,
    is_encrypted: item["is_encrypted"] === true,
    status: str(item["status"]) ?? "active",
    is_required: item["is_required"] === true,
    is_unique: item["is_unique"] === true,
    position: num(item["position"]) ?? 0,
    version: num(item["version"]) ?? 1,
    rules: parseRules(item["rules"]),
  };
}

export function parseCustomFields(value: unknown): CustomFieldDefinition[] {
  if (!isRec(value)) throw invalid();
  return items(value["items"], parseCustomField);
}
