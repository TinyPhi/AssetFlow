// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// The asset list's service functions over `lib/api` (§C4.9) and its query-key factory. Hooks call these;
// components never call `fetch`.
import { apiFetch } from "@/lib/api";
import type {
  AssetPage,
  CustomFieldDefinition,
  HierarchyNode,
  SavedView,
  SavedViewQuery,
  TeamOption,
} from "../types";
import {
  parseAssetPage,
  parseCustomFields,
  parseHierarchyList,
  parseSavedView,
  parseSavedViews,
  parseTeams,
} from "./parsers";

export const assetKeys = {
  all: () => ["assets"] as const,
  lists: () => ["assets", "list"] as const,
  list: (query: string) => ["assets", "list", query] as const,
  views: () => ["assets", "saved-views"] as const,
  categories: () => ["assets", "lookups", "categories"] as const,
  orgUnits: () => ["assets", "lookups", "org-units"] as const,
  locations: () => ["assets", "lookups", "locations"] as const,
  teams: () => ["assets", "lookups", "teams"] as const,
  customFields: (categoryId: string) => ["assets", "lookups", "custom-fields", categoryId] as const,
  detail: (id: string) => ["assets", "detail", id] as const,
  transitions: (id: string) => ["assets", "detail", id, "transitions"] as const,
  components: (id: string) => ["assets", "detail", id, "components"] as const,
  vocabulary: () => ["assets", "lookups", "vocabulary"] as const,
  parties: (kind: string, status: string) => ["assets", "lookups", kind, status] as const,
  categoryRecords: (status: string) => ["assets", "lookups", "category-records", status] as const,
  fieldDefinitions: (categoryId: string, status: string) =>
    ["assets", "lookups", "field-definitions", categoryId, status] as const,
} as const;

/** One page of the list; `query` is the already serialized parameter string (see `toApiParams`). */
export async function fetchAssetPage(query: string, signal?: AbortSignal): Promise<AssetPage> {
  const data = await apiFetch<unknown>(`/assets?${query}`, signal === undefined ? {} : { signal });
  return parseAssetPage(data);
}

export async function fetchSavedViews(): Promise<SavedView[]> {
  return parseSavedViews(await apiFetch<unknown>("/asset-saved-views"));
}

export interface SavedViewInput {
  name: string;
  query: SavedViewQuery;
  sort: string;
  columns: string[];
}

export async function createSavedView(input: SavedViewInput): Promise<SavedView> {
  const data = await apiFetch<unknown>("/asset-saved-views", { method: "POST", body: input });
  const view = parseSavedView(data);
  if (view === null) throw new Error("invalid saved view");
  return view;
}

export async function renameSavedView(view: SavedView, name: string): Promise<SavedView> {
  const data = await apiFetch<unknown>(`/asset-saved-views/${view.id}`, {
    method: "PATCH",
    body: { version: view.version, name },
  });
  const updated = parseSavedView(data);
  if (updated === null) throw new Error("invalid saved view");
  return updated;
}

export async function deleteSavedView(id: string): Promise<void> {
  await apiFetch<unknown>(`/asset-saved-views/${id}`, { method: "DELETE" });
}

const MAX_LOOKUP_PAGES = 20;

/** Every category: the endpoint is a cursor page, so the pages are read until the cursor ends. */
export async function fetchCategories(): Promise<HierarchyNode[]> {
  const nodes: HierarchyNode[] = [];
  let after: string | null = null;
  for (let page = 0; page < MAX_LOOKUP_PAGES; page += 1) {
    const suffix: string = after === null ? "" : `&after=${encodeURIComponent(after)}`;
    const result = parseHierarchyList(
      await apiFetch<unknown>(`/asset-categories?status=active&limit=100${suffix}`),
    );
    nodes.push(...result.nodes);
    if (result.next === null) break;
    after = result.next;
  }
  return nodes;
}

export async function fetchOrgUnits(): Promise<HierarchyNode[]> {
  return parseHierarchyList(await apiFetch<unknown>("/org-units?status=active")).nodes;
}

export async function fetchLocations(): Promise<HierarchyNode[]> {
  return parseHierarchyList(await apiFetch<unknown>("/locations")).nodes;
}

export async function fetchTeams(): Promise<TeamOption[]> {
  return parseTeams(await apiFetch<unknown>("/teams?status=active"));
}

/** The category's filterable custom fields: active and not encrypted (an encrypted field is never filterable). */
export async function fetchFilterableFields(categoryId: string): Promise<CustomFieldDefinition[]> {
  const data = await apiFetch<unknown>(
    `/asset-categories/${categoryId}/custom-fields?status=active&limit=100`,
  );
  return parseCustomFields(data).filter((field) => !field.is_encrypted && field.field_type !== "json");
}
