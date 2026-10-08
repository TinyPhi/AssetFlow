// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Narrowing of unknown API JSON for the asset detail, the vocabulary, components and the catalog
// administration screens. A malformed envelope throws (the screen's error state shows it); a malformed
// list item is dropped rather than shown half-filled.
import type {
  AssetDetail,
  AssetParent,
  CategoryRecord,
  ComponentChild,
  EncryptedView,
  PartyRecord,
  Transition,
  Vocabulary,
} from "../types";
import { invalid, isRec, items, str, strOrNull, type Rec } from "./parsers";

function num(value: unknown, fallback: number): number {
  return typeof value === "number" ? value : fallback;
}

function holder(value: unknown): AssetDetail["holder"] {
  if (!isRec(value)) return null;
  const type = value["type"];
  const id = str(value["id"]);
  const name = str(value["display_name"]);
  if ((type !== "member" && type !== "team" && type !== "location") || id === null || name === null) {
    return null;
  }
  return { type, id, display_name: name };
}

function parent(value: unknown): AssetParent | null {
  if (!isRec(value)) return null;
  const id = str(value["id"]);
  const tag = str(value["tag"]);
  const name = str(value["name"]);
  return id !== null && tag !== null && name !== null ? { id, tag, name } : null;
}

/** An encrypted field is `{is_set}` without the sensitive permission, otherwise its decrypted value. */
function encryptedView(value: unknown): EncryptedView {
  const view: EncryptedView = {};
  if (!isRec(value)) return view;
  for (const [key, entry] of Object.entries(value)) {
    const keys = isRec(entry) ? Object.keys(entry) : [];
    if (isRec(entry) && keys.length === 1 && typeof entry["is_set"] === "boolean") {
      view[key] = { is_set: entry["is_set"] };
    } else {
      view[key] = { value: entry };
    }
  }
  return view;
}

export function parseAssetDetail(value: unknown): AssetDetail {
  if (!isRec(value)) throw invalid();
  const id = str(value["id"]);
  const tag = str(value["tag"]);
  const name = str(value["name"]);
  const status = str(value["status"]);
  const categoryId = str(value["category_id"]);
  const ownerId = str(value["owner_org_unit_id"]);
  if (id === null || tag === null || name === null || status === null) throw invalid();
  if (categoryId === null || ownerId === null) throw invalid();
  const custom: Rec = isRec(value["custom_fields"]) ? value["custom_fields"] : {};
  const cost = value["purchase_cost"];
  return {
    id,
    tag,
    name,
    category_id: categoryId,
    category_name: str(value["category_name"]) ?? "",
    model: strOrNull(value["model"]),
    manufacturer_id: strOrNull(value["manufacturer_id"]),
    manufacturer_name: strOrNull(value["manufacturer_name"]),
    supplier_id: strOrNull(value["supplier_id"]),
    supplier_name: strOrNull(value["supplier_name"]),
    serial_number: strOrNull(value["serial_number"]),
    owner_org_unit_id: ownerId,
    owner_org_unit_name: str(value["owner_org_unit_name"]) ?? "",
    location_id: strOrNull(value["location_id"]),
    location_name: strOrNull(value["location_name"]),
    holder: holder(value["holder"]),
    status,
    criticality: strOrNull(value["criticality"]),
    purchase_date: strOrNull(value["purchase_date"]),
    purchase_cost: typeof cost === "string" ? cost : typeof cost === "number" ? String(cost) : null,
    warranty_end: strOrNull(value["warranty_end"]),
    custom_fields: custom,
    encrypted_fields: encryptedView(value["encrypted_fields"]),
    notes: strOrNull(value["notes"]),
    parent: parent(value["parent"]),
    component_count: num(value["component_count"], 0),
    version: num(value["version"], 1),
    created_at: str(value["created_at"]) ?? "",
    updated_at: str(value["updated_at"]) ?? "",
  };
}

export function parseVocabulary(value: unknown): Vocabulary {
  if (!isRec(value)) throw invalid();
  const status = (item: unknown): Vocabulary["statuses"][number] | null => {
    if (!isRec(item)) return null;
    const key = str(item["key"]);
    const label = str(item["label"]);
    return key !== null && label !== null ? { key, label, category: str(item["category"]) ?? "" } : null;
  };
  const levels = Array.isArray(value["criticality"])
    ? (value["criticality"] as unknown[]).filter((l): l is string => typeof l === "string")
    : [];
  return { statuses: items(value["statuses"], status), criticality: levels };
}

export function parseTransitions(value: unknown): Transition[] {
  if (!isRec(value)) throw invalid();
  const parse = (item: unknown): Transition | null => {
    if (!isRec(item)) return null;
    const to = str(item["to_status"]);
    const label = str(item["to_label"]);
    return to !== null && label !== null
      ? { to_status: to, to_label: label, requires_reason: item["requires_reason"] === true }
      : null;
  };
  return items(value["items"], parse);
}

export function parseComponents(value: unknown): ComponentChild[] {
  if (!isRec(value)) throw invalid();
  const parse = (item: unknown): ComponentChild | null => {
    if (!isRec(item)) return null;
    const componentId = str(item["component_id"]);
    const childId = str(item["child_asset_id"]);
    const tag = str(item["tag"]);
    const name = str(item["name"]);
    if (componentId === null || childId === null || tag === null || name === null) return null;
    return {
      component_id: componentId,
      child_asset_id: childId,
      tag,
      name,
      status: str(item["status"]) ?? "",
      attached_at: str(item["attached_at"]) ?? "",
      detached_at: strOrNull(item["detached_at"]),
    };
  };
  return items(value["items"], parse);
}

export function parseCategory(item: unknown): CategoryRecord | null {
  if (!isRec(item)) return null;
  const id = str(item["id"]);
  const name = str(item["name"]);
  if (id === null || name === null) return null;
  return {
    id,
    name,
    parent_id: strOrNull(item["parent_id"]),
    path: str(item["path"]) ?? "",
    code: str(item["code"]) ?? "",
    tag_prefix: strOrNull(item["tag_prefix"]),
    default_criticality: strOrNull(item["default_criticality"]),
    responsible_team_id: strOrNull(item["responsible_team_id"]),
    status: str(item["status"]) ?? "active",
    version: num(item["version"], 1),
  };
}

export function parseCategoryPage(value: unknown): { items: CategoryRecord[]; next: string | null } {
  if (!isRec(value)) throw invalid();
  return { items: items(value["items"], parseCategory), next: strOrNull(value["next_cursor"]) };
}

export function parseParty(item: unknown): PartyRecord | null {
  if (!isRec(item)) return null;
  const id = str(item["id"]);
  const name = str(item["name"]);
  if (id === null || name === null) return null;
  return {
    id,
    name,
    code: strOrNull(item["code"]),
    notes: strOrNull(item["notes"]),
    status: str(item["status"]) ?? "active",
    version: num(item["version"], 1),
  };
}

export function parsePartyPage(value: unknown): { items: PartyRecord[]; next: string | null } {
  if (!isRec(value)) throw invalid();
  return { items: items(value["items"], parseParty), next: strOrNull(value["next_cursor"]) };
}
