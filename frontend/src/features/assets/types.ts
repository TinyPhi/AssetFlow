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

export interface CustomFieldDefinition {
  id: string;
  key: string;
  label: string;
  field_type: string;
  is_encrypted: boolean;
  status: string;
}
