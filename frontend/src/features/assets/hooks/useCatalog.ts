// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { assetKeys } from "../api/assets";
import {
  archiveCategory,
  archiveFieldDefinition,
  archiveParty,
  createCategory,
  createFieldDefinition,
  createParty,
  fetchCategoryRecords,
  fetchFieldDefinitions,
  fetchParties,
  moveCategory,
  updateCategory,
  updateFieldDefinition,
  updateParty,
  type CategoryCreateInput,
  type CategoryUpdateInput,
  type FieldCreateInput,
  type FieldUpdateInput,
  type PartyInput,
} from "../api/catalog";
import type { CategoryRecord, CustomFieldDefinition, PartyKind, PartyRecord } from "../types";

const LOOKUP_STALE_MS = 60_000;

/** Categories of one status; `""` reads every status. */
export function useCategoryRecords(status: string, enabled = true): UseQueryResult<CategoryRecord[]> {
  return useQuery({
    queryKey: assetKeys.categoryRecords(status),
    queryFn: () => fetchCategoryRecords(status),
    enabled,
    staleTime: LOOKUP_STALE_MS,
  });
}

/** A category's custom field definitions of one status; `""` reads every status. */
export function useFieldDefinitions(
  categoryId: string,
  status: string,
): UseQueryResult<CustomFieldDefinition[]> {
  return useQuery({
    queryKey: assetKeys.fieldDefinitions(categoryId, status),
    queryFn: () => fetchFieldDefinitions(categoryId, status),
    enabled: categoryId !== "",
    staleTime: LOOKUP_STALE_MS,
  });
}

export function useParties(kind: PartyKind, status: string, enabled = true): UseQueryResult<PartyRecord[]> {
  return useQuery({
    queryKey: assetKeys.parties(kind, status),
    queryFn: () => fetchParties(kind, status),
    enabled,
    staleTime: LOOKUP_STALE_MS,
  });
}

/** A catalog write marks every catalog lookup stale (the asset form and the filters read them too). */
function useCatalogRefresh(): () => Promise<void> {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: ["assets", "lookups"] });
}

export function useCategoryMutations() {
  const refresh = useCatalogRefresh();
  const options = { onSuccess: refresh };
  const create = useMutation({
    mutationFn: (input: CategoryCreateInput) => createCategory(input),
    ...options,
  });
  const update = useMutation({
    mutationFn: ({ id, input }: { id: string; input: CategoryUpdateInput }) => updateCategory(id, input),
    ...options,
  });
  const move = useMutation({
    mutationFn: ({ id, parentId, version }: { id: string; parentId: string; version: number }) =>
      moveCategory(id, parentId, version),
    ...options,
  });
  const archive = useMutation({
    mutationFn: ({ id, version }: { id: string; version: number }) => archiveCategory(id, version),
    ...options,
  });
  return { create, update, move, archive };
}

export function useFieldMutations(categoryId: string) {
  const refresh = useCatalogRefresh();
  const options = { onSuccess: refresh };
  const create = useMutation({
    mutationFn: (input: FieldCreateInput) => createFieldDefinition(categoryId, input),
    ...options,
  });
  const update = useMutation({
    mutationFn: ({ id, input }: { id: string; input: FieldUpdateInput }) =>
      updateFieldDefinition(categoryId, id, input),
    ...options,
  });
  const archive = useMutation({
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      archiveFieldDefinition(categoryId, id, version),
    ...options,
  });
  return { create, update, archive };
}

export function usePartyMutations(kind: PartyKind) {
  const refresh = useCatalogRefresh();
  const options = { onSuccess: refresh };
  const create = useMutation({ mutationFn: (input: PartyInput) => createParty(kind, input), ...options });
  const update = useMutation({
    mutationFn: ({ id, input }: { id: string; input: Record<string, unknown> & { version: number } }) =>
      updateParty(kind, id, input),
    ...options,
  });
  const archive = useMutation({
    mutationFn: ({ id, version }: { id: string; version: number }) => archiveParty(kind, id, version),
    ...options,
  });
  return { create, update, archive };
}
