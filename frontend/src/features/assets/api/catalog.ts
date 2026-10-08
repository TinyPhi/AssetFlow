// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Catalog administration service functions: categories, custom field definitions, manufacturers and
// suppliers (§B8.1, P8-06). Reads follow the cursor until it ends (bounded); writes carry `version`.
import { apiFetch } from "@/lib/api";
import type { CategoryRecord, CustomFieldDefinition, PartyKind, PartyRecord } from "../types";
import { parseCategory, parseCategoryPage, parseParty, parsePartyPage } from "./detail-parsers";
import { parseCustomField, parseCustomFields } from "./parsers";

const MAX_PAGES = 20;

function requireOne<T>(value: T | null): T {
  if (value === null) throw new Error("invalid response");
  return value;
}

async function readAll<T>(
  path: string,
  parse: (data: unknown) => { items: T[]; next: string | null },
): Promise<T[]> {
  const all: T[] = [];
  let after: string | null = null;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const suffix: string = after === null ? "" : `&after=${encodeURIComponent(after)}`;
    const result = parse(await apiFetch<unknown>(`${path}${suffix}`));
    all.push(...result.items);
    if (result.next === null) break;
    after = result.next;
  }
  return all;
}

function statusFilter(status: string): string {
  return status === "" ? "" : `status=${status}&`;
}

/** Categories of one status (`""` for every status). */
export async function fetchCategoryRecords(status: string): Promise<CategoryRecord[]> {
  return readAll(`/asset-categories?${statusFilter(status)}limit=100`, parseCategoryPage);
}

export interface CategoryCreateInput {
  code: string;
  name: string;
  parent_id?: string;
  tag_prefix?: string;
  default_criticality?: string;
}

export async function createCategory(input: CategoryCreateInput): Promise<CategoryRecord> {
  const data = await apiFetch<unknown>("/asset-categories", { method: "POST", body: input });
  return requireOne(parseCategory(data));
}

export type CategoryUpdateInput = Record<string, unknown> & { version: number };

export async function updateCategory(id: string, input: CategoryUpdateInput): Promise<CategoryRecord> {
  const data = await apiFetch<unknown>(`/asset-categories/${id}`, { method: "PATCH", body: input });
  return requireOne(parseCategory(data));
}

export async function moveCategory(
  id: string,
  newParentId: string,
  version: number,
): Promise<CategoryRecord> {
  const data = await apiFetch<unknown>(`/asset-categories/${id}/move`, {
    method: "POST",
    body: { new_parent_id: newParentId, version },
  });
  return requireOne(parseCategory(data));
}

export async function archiveCategory(id: string, version: number): Promise<CategoryRecord> {
  const data = await apiFetch<unknown>(`/asset-categories/${id}/archive`, {
    method: "POST",
    body: { version },
  });
  return requireOne(parseCategory(data));
}

export async function fetchFieldDefinitions(
  categoryId: string,
  status: string,
): Promise<CustomFieldDefinition[]> {
  const data = await apiFetch<unknown>(
    `/asset-categories/${categoryId}/custom-fields?${statusFilter(status)}limit=100`,
  );
  return parseCustomFields(data).sort((a, b) => a.position - b.position);
}

export interface FieldCreateInput {
  key: string;
  label: string;
  field_type: string;
  is_required: boolean;
  is_unique: boolean;
  is_encrypted: boolean;
  min?: number;
  max?: number;
  regex?: string;
  options?: string[];
  position?: number;
}

export async function createFieldDefinition(
  categoryId: string,
  input: FieldCreateInput,
): Promise<CustomFieldDefinition> {
  const data = await apiFetch<unknown>(`/asset-categories/${categoryId}/custom-fields`, {
    method: "POST",
    body: input,
  });
  return requireOne(parseCustomField(data));
}

export type FieldUpdateInput = Record<string, unknown> & { version: number };

export async function updateFieldDefinition(
  categoryId: string,
  fieldId: string,
  input: FieldUpdateInput,
): Promise<CustomFieldDefinition> {
  const data = await apiFetch<unknown>(`/asset-categories/${categoryId}/custom-fields/${fieldId}`, {
    method: "PATCH",
    body: input,
  });
  return requireOne(parseCustomField(data));
}

export async function archiveFieldDefinition(
  categoryId: string,
  fieldId: string,
  version: number,
): Promise<CustomFieldDefinition> {
  const data = await apiFetch<unknown>(`/asset-categories/${categoryId}/custom-fields/${fieldId}/archive`, {
    method: "POST",
    body: { version },
  });
  return requireOne(parseCustomField(data));
}

export async function fetchParties(kind: PartyKind, status: string): Promise<PartyRecord[]> {
  return readAll(`/${kind}?${statusFilter(status)}limit=100`, parsePartyPage);
}

export interface PartyInput {
  name: string;
  code?: string;
  notes?: string;
}

export async function createParty(kind: PartyKind, input: PartyInput): Promise<PartyRecord> {
  return requireOne(parseParty(await apiFetch<unknown>(`/${kind}`, { method: "POST", body: input })));
}

export async function updateParty(
  kind: PartyKind,
  id: string,
  input: Record<string, unknown> & { version: number },
): Promise<PartyRecord> {
  return requireOne(parseParty(await apiFetch<unknown>(`/${kind}/${id}`, { method: "PATCH", body: input })));
}

export async function archiveParty(kind: PartyKind, id: string, version: number): Promise<PartyRecord> {
  const data = await apiFetch<unknown>(`/${kind}/${id}/archive`, { method: "POST", body: { version } });
  return requireOne(parseParty(data));
}
