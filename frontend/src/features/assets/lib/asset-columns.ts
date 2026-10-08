// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { TranslationKey } from "@/lib/i18n";
import type { SortKey } from "./asset-filter-params";

export interface ColumnDef {
  id: string;
  labelKey: TranslationKey;
  /** The API sort key when the column can be sorted (the API's allowlist). */
  sort?: SortKey;
}

/** The columns the list can show, in display order; each is an `AssetListItem` field the API returns. */
export const COLUMNS = [
  { id: "tag", labelKey: "assets.columns.tag", sort: "tag" },
  { id: "name", labelKey: "assets.columns.name", sort: "name" },
  { id: "status", labelKey: "assets.columns.status", sort: "status" },
  { id: "category_name", labelKey: "assets.columns.category_name" },
  { id: "holder", labelKey: "assets.columns.holder" },
  { id: "owner_org_unit_name", labelKey: "assets.columns.owner_org_unit_name" },
  { id: "location_name", labelKey: "assets.columns.location_name" },
  { id: "criticality", labelKey: "assets.columns.criticality" },
  { id: "warranty_end", labelKey: "assets.columns.warranty_end", sort: "warranty_end" },
  { id: "model", labelKey: "assets.columns.model" },
  { id: "serial_number", labelKey: "assets.columns.serial_number" },
  { id: "updated_at", labelKey: "assets.columns.updated_at", sort: "updated_at" },
] as const satisfies readonly ColumnDef[];

export type ColumnId = (typeof COLUMNS)[number]["id"];

export const COLUMN_IDS: readonly ColumnId[] = COLUMNS.map((column) => column.id);

export const DEFAULT_COLUMNS: readonly ColumnId[] = [
  "tag",
  "name",
  "status",
  "category_name",
  "holder",
  "owner_org_unit_name",
];

export function columnDef(id: ColumnId): ColumnDef {
  return COLUMNS.find((column) => column.id === id) ?? COLUMNS[0];
}
