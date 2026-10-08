// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// The asset list's data shapes as the API sends them (backend/app/modules/assets/schemas.py,
// saved_views.py, catalog/schemas.py). Field names stay snake_case as received (§C1.3).

export type HolderType = "member" | "team" | "location";

export interface AssetHolder {
  type: HolderType;
  id: string;
  display_name: string;
}

export interface AssetListItem {
  id: string;
  tag: string;
  name: string;
  category_id: string;
  category_name: string;
  model: string | null;
  manufacturer_name: string | null;
  serial_number: string | null;
  owner_org_unit_id: string;
  owner_org_unit_name: string;
  location_id: string | null;
  location_name: string | null;
  holder: AssetHolder | null;
  status: string;
  criticality: string | null;
  warranty_end: string | null;
  purchase_date: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface AssetPage {
  items: AssetListItem[];
  next_cursor: string | null;
  total: number | null;
}

/** A saved view's query: the list's own query parameters, scalars or lists of scalars. */
export type SavedViewQuery = Record<string, string | number | boolean | (string | number | boolean)[]>;

export interface SavedView {
  id: string;
  name: string;
  query: SavedViewQuery;
  sort: string;
  columns: string[];
  version: number;
}

/** A category, org unit or location: the three hierarchies share this shape for the pickers. */
export interface HierarchyNode {
  id: string;
  parent_id: string | null;
  path: string;
  name: string;
}

export interface TeamOption {
  id: string;
  name: string;
}

/** A custom field definition as the API sends it (§B8.1); the rules are the wire's `rules` object. */
export interface CustomFieldDefinition {
  id: string;
  key: string;
  label: string;
  field_type: string;
  is_encrypted: boolean;
  status: string;
  is_required: boolean;
  is_unique: boolean;
  position: number;
  version: number;
  rules: CustomFieldRules;
}

export interface CustomFieldRules {
  min: number | null;
  max: number | null;
  regex: string | null;
  options: string[];
}

export const CUSTOM_FIELD_TYPES = [
  "text",
  "number",
  "date",
  "boolean",
  "select",
  "multi_select",
  "json",
] as const;
export type CustomFieldType = (typeof CUSTOM_FIELD_TYPES)[number];

export function isCustomFieldType(value: string): value is CustomFieldType {
  return (CUSTOM_FIELD_TYPES as readonly string[]).includes(value);
}

/** A category with its own settings (the pickers only need the `HierarchyNode` part). */
export interface CategoryRecord extends HierarchyNode {
  code: string;
  tag_prefix: string | null;
  default_criticality: string | null;
  responsible_team_id: string | null;
  status: string;
  version: number;
}

/** A manufacturer or a supplier: the two share one shape. */
export interface PartyRecord {
  id: string;
  code: string | null;
  name: string;
  notes: string | null;
  status: string;
  version: number;
}

export type PartyKind = "manufacturers" | "suppliers";

export interface StatusInfo {
  key: string;
  label: string;
  category: string;
}

/** The organization's status labels and criticality levels (template data). */
export interface Vocabulary {
  statuses: StatusInfo[];
  criticality: string[];
}

export interface Transition {
  to_status: string;
  to_label: string;
  requires_reason: boolean;
}

export interface AssetParent {
  id: string;
  tag: string;
  name: string;
}

/** Encrypted values: presence only without `asset.read_sensitive`, the typed value with it. */
export type EncryptedView = Record<string, { is_set: boolean } | { value: unknown }>;

export interface AssetDetail {
  id: string;
  tag: string;
  name: string;
  category_id: string;
  category_name: string;
  model: string | null;
  manufacturer_id: string | null;
  manufacturer_name: string | null;
  supplier_id: string | null;
  supplier_name: string | null;
  serial_number: string | null;
  owner_org_unit_id: string;
  owner_org_unit_name: string;
  location_id: string | null;
  location_name: string | null;
  holder: AssetHolder | null;
  status: string;
  criticality: string | null;
  purchase_date: string | null;
  purchase_cost: string | null;
  warranty_end: string | null;
  custom_fields: Record<string, unknown>;
  encrypted_fields: EncryptedView;
  notes: string | null;
  parent: AssetParent | null;
  component_count: number;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ComponentChild {
  component_id: string;
  child_asset_id: string;
  tag: string;
  name: string;
  status: string;
  attached_at: string;
  detached_at: string | null;
}
