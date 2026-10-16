// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// The asset list's query rules as pure functions (M2.1-T5). The URL query string, the API request and a
// saved view's `query` all use the API's own parameter names, so one parse and one serialize serve all
// three. Rules (ported from AssetManager's `assetFilterParams`): empty values are dropped, a sub-tree
// switch needs its parent filter, a holder id needs its holder type, custom-field filters need a category,
// and an unknown sort or holder type falls back to the default.
import type { HolderType, SavedViewQuery } from "../types";

export const DEFAULT_SORT = "-created_at";
export const DEFAULT_PAGE_SIZE = 50;

/** The API's sort allowlist (repository `SORT_COLUMNS`); a leading `-` sorts descending. */
export const SORT_KEYS = [
  "tag",
  "name",
  "status",
  "created_at",
  "updated_at",
  "warranty_end",
  "purchase_date",
] as const;
export type SortKey = (typeof SORT_KEYS)[number];

export const HOLDER_TYPES: readonly HolderType[] = ["member", "team", "location"];
export const STATUS_CATEGORIES = ["available", "in_use", "unavailable", "ended"] as const;

const CUSTOM_FIELD_PARAM = /^cf\.[a-z][a-z0-9_]*(\.(gte|lte))?$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export interface AssetFilters {
  q: string;
  status: string[];
  statusCategory: string;
  categoryId: string;
  includeSubcategories: boolean;
  ownerOrgUnitId: string;
  includeSubUnits: boolean;
  locationId: string;
  includeSubLocations: boolean;
  holderType: HolderType | "";
  holderTeamId: string;
  criticality: string[];
  warrantyEndAfter: string;
  warrantyEndBefore: string;
  /** Custom-field filters keyed by their parameter name (`cf.<key>`, `cf.<key>.gte`, `cf.<key>.lte`). */
  custom: Record<string, string>;
}

export interface AssetListState {
  filters: AssetFilters;
  sort: string;
}

export function emptyFilters(): AssetFilters {
  return {
    q: "",
    status: [],
    statusCategory: "",
    categoryId: "",
    includeSubcategories: false,
    ownerOrgUnitId: "",
    includeSubUnits: false,
    locationId: "",
    includeSubLocations: false,
    holderType: "",
    holderTeamId: "",
    criticality: [],
    warrantyEndAfter: "",
    warrantyEndBefore: "",
    custom: {},
  };
}

export function isSortValid(sort: string): boolean {
  return (SORT_KEYS as readonly string[]).includes(sort.replace(/^-/, ""));
}

function isHolderType(value: string): value is HolderType {
  return (HOLDER_TYPES as readonly string[]).includes(value);
}

function unique(values: readonly string[]): string[] {
  return [...new Set(values.map((v) => v.trim()).filter((v) => v !== ""))];
}

function isDate(value: string): boolean {
  return ISO_DATE.test(value);
}

/** Apply the dependency rules, so a state never carries a value its parent filter makes meaningless. */
export function normalizeFilters(input: AssetFilters): AssetFilters {
  const holderType = input.holderType;
  const custom: Record<string, string> = {};
  if (input.categoryId !== "") {
    for (const [key, value] of Object.entries(input.custom)) {
      if (CUSTOM_FIELD_PARAM.test(key) && value.trim() !== "") custom[key] = value.trim();
    }
  }
  return {
    q: input.q.trim(),
    status: unique(input.status),
    statusCategory: input.statusCategory,
    categoryId: input.categoryId,
    includeSubcategories: input.categoryId !== "" && input.includeSubcategories,
    ownerOrgUnitId: input.ownerOrgUnitId,
    includeSubUnits: input.ownerOrgUnitId !== "" && input.includeSubUnits,
    locationId: input.locationId,
    includeSubLocations: input.locationId !== "" && input.includeSubLocations,
    holderType,
    holderTeamId: holderType === "team" ? input.holderTeamId : "",
    criticality: unique(input.criticality),
    warrantyEndAfter: isDate(input.warrantyEndAfter) ? input.warrantyEndAfter : "",
    warrantyEndBefore: isDate(input.warrantyEndBefore) ? input.warrantyEndBefore : "",
    custom,
  };
}

/** Read a list state from query parameters (the URL's, or a saved view's turned into some). */
export function parseListState(params: URLSearchParams): AssetListState {
  const text = (name: string): string => params.get(name) ?? "";
  const flag = (name: string): boolean => params.get(name) === "true";
  const holder = text("holder_type");
  const custom: Record<string, string> = {};
  for (const [name, value] of params.entries()) {
    if (CUSTOM_FIELD_PARAM.test(name)) custom[name] = value;
  }
  const sort = text("sort");
  return {
    filters: normalizeFilters({
      q: text("q"),
      status: params.getAll("status"),
      statusCategory: (STATUS_CATEGORIES as readonly string[]).includes(text("status_category"))
        ? text("status_category")
        : "",
      categoryId: text("category_id"),
      includeSubcategories: flag("include_subcategories"),
      ownerOrgUnitId: text("owner_org_unit_id"),
      includeSubUnits: flag("include_sub_units"),
      locationId: text("location_id"),
      includeSubLocations: flag("include_sub_locations"),
      holderType: isHolderType(holder) ? holder : "",
      holderTeamId: text("holder_team_id"),
      criticality: params.getAll("criticality"),
      warrantyEndAfter: text("warranty_end_after"),
      warrantyEndBefore: text("warranty_end_before"),
      custom,
    }),
    sort: isSortValid(sort) ? sort : DEFAULT_SORT,
  };
}

/** The filters as API parameters, in a stable order; the default sort is left out. */
export function toSearchParams(state: AssetListState): URLSearchParams {
  const f = normalizeFilters(state.filters);
  const params = new URLSearchParams();
  const put = (name: string, value: string): void => {
    if (value !== "") params.set(name, value);
  };
  const putFlag = (name: string, value: boolean): void => {
    if (value) params.set(name, "true");
  };
  put("q", f.q);
  for (const value of f.status) params.append("status", value);
  put("status_category", f.statusCategory);
  put("category_id", f.categoryId);
  putFlag("include_subcategories", f.includeSubcategories);
  put("owner_org_unit_id", f.ownerOrgUnitId);
  putFlag("include_sub_units", f.includeSubUnits);
  put("location_id", f.locationId);
  putFlag("include_sub_locations", f.includeSubLocations);
  put("holder_type", f.holderType);
  put("holder_team_id", f.holderTeamId);
  for (const value of f.criticality) params.append("criticality", value);
  put("warranty_end_after", f.warrantyEndAfter);
  put("warranty_end_before", f.warrantyEndBefore);
  for (const key of Object.keys(f.custom).sort()) put(key, f.custom[key] ?? "");
  if (state.sort !== DEFAULT_SORT && isSortValid(state.sort)) params.set("sort", state.sort);
  return params;
}

/** The request for one page: the filters, the sort (always explicit), the cursor and the page size. */
export function toApiParams(
  state: AssetListState,
  page: { after?: string | undefined; limit?: number } = {},
): URLSearchParams {
  const params = toSearchParams(state);
  params.set("sort", isSortValid(state.sort) ? state.sort : DEFAULT_SORT);
  if (page.after !== undefined) params.set("after", page.after);
  params.set("limit", String(page.limit ?? DEFAULT_PAGE_SIZE));
  return params;
}

/** A saved view's `query`: the filters only (the sort is stored beside it). */
export function toViewQuery(filters: AssetFilters): SavedViewQuery {
  const params = toSearchParams({ filters, sort: DEFAULT_SORT });
  const query: SavedViewQuery = {};
  for (const name of new Set(params.keys())) {
    const values = params.getAll(name);
    const first = values[0] ?? "";
    query[name] = name === "status" || name === "criticality" ? values : first === "true" ? true : first;
  }
  return query;
}

/** The list state a saved view stands for (applying a view rewrites the URL from this). */
export function stateFromView(view: { query: SavedViewQuery; sort: string }): AssetListState {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(view.query)) {
    for (const v of Array.isArray(value) ? value : [value]) params.append(name, String(v));
  }
  params.set("sort", view.sort);
  return parseListState(params);
}

export type ChipField =
  | "status"
  | "statusCategory"
  | "categoryId"
  | "ownerOrgUnitId"
  | "locationId"
  | "holderType"
  | "holderTeamId"
  | "criticality"
  | "warrantyEndAfter"
  | "warrantyEndBefore"
  | "custom";

/** One removable filter: `value` is the multi-value entry or the custom-field parameter name. */
export interface FilterChip {
  id: string;
  field: ChipField;
  value: string;
}

/** The chips for the filters in force (the search text is shown in the search box, not as a chip). */
export function activeChips(filters: AssetFilters): FilterChip[] {
  const f = normalizeFilters(filters);
  const chips: FilterChip[] = [];
  const add = (field: ChipField, value: string): void => {
    if (value !== "") chips.push({ id: `${field}:${value}`, field, value });
  };
  for (const value of f.status) add("status", value);
  add("statusCategory", f.statusCategory);
  add("categoryId", f.categoryId);
  add("ownerOrgUnitId", f.ownerOrgUnitId);
  add("locationId", f.locationId);
  add("holderType", f.holderType);
  add("holderTeamId", f.holderTeamId);
  for (const value of f.criticality) add("criticality", value);
  add("warrantyEndAfter", f.warrantyEndAfter);
  add("warrantyEndBefore", f.warrantyEndBefore);
  for (const key of Object.keys(f.custom)) add("custom", key);
  return chips;
}

/** The filters with one chip cleared (removing a parent filter also clears what depended on it). */
export function removeChip(filters: AssetFilters, chip: FilterChip): AssetFilters {
  const next: AssetFilters = { ...filters };
  switch (chip.field) {
    case "status":
      next.status = filters.status.filter((v) => v !== chip.value);
      break;
    case "statusCategory":
      next.statusCategory = "";
      break;
    case "categoryId":
      next.categoryId = "";
      break;
    case "ownerOrgUnitId":
      next.ownerOrgUnitId = "";
      break;
    case "locationId":
      next.locationId = "";
      break;
    case "holderType":
      next.holderType = "";
      break;
    case "holderTeamId":
      next.holderTeamId = "";
      break;
    case "criticality":
      next.criticality = filters.criticality.filter((v) => v !== chip.value);
      break;
    case "warrantyEndAfter":
      next.warrantyEndAfter = "";
      break;
    case "warrantyEndBefore":
      next.warrantyEndBefore = "";
      break;
    case "custom":
      next.custom = Object.fromEntries(Object.entries(filters.custom).filter(([k]) => k !== chip.value));
      break;
  }
  return normalizeFilters(next);
}

/** Every filter cleared; the search text stays unless `keepSearch` is false. */
export function clearFilters(filters: AssetFilters, keepSearch = true): AssetFilters {
  return { ...emptyFilters(), q: keepSearch ? filters.q : "" };
}

/** Whether any filter other than the search text is in force. */
export function hasActiveFilters(filters: AssetFilters): boolean {
  return activeChips(filters).length > 0;
}

/** `in_use` becomes `In use`: a readable fallback for a key the API gave no label for. */
export function humanizeKey(key: string): string {
  const spaced = key.replaceAll("_", " ").trim();
  return spaced === "" ? "" : spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Next sort when a column heading is chosen: ascending first, then descending, then ascending again. */
export function nextSort(current: string, key: SortKey): string {
  return current === key ? `-${key}` : key;
}
