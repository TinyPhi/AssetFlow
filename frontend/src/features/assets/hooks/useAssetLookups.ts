// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import {
  assetKeys,
  fetchCategories,
  fetchFilterableFields,
  fetchLocations,
  fetchOrgUnits,
  fetchTeams,
} from "../api/assets";
import type { CustomFieldDefinition, HierarchyNode, TeamOption } from "../types";

const LOOKUP_STALE_MS = 5 * 60_000;

// The pickers' option lists. A lookup that fails (for example a member who may not read org units)
// leaves its picker without options; the list itself never waits on them.
export function useCategories(): UseQueryResult<HierarchyNode[]> {
  return useQuery({ queryKey: assetKeys.categories(), queryFn: fetchCategories, staleTime: LOOKUP_STALE_MS });
}

export function useOrgUnits(): UseQueryResult<HierarchyNode[]> {
  return useQuery({ queryKey: assetKeys.orgUnits(), queryFn: fetchOrgUnits, staleTime: LOOKUP_STALE_MS });
}

export function useLocations(): UseQueryResult<HierarchyNode[]> {
  return useQuery({ queryKey: assetKeys.locations(), queryFn: fetchLocations, staleTime: LOOKUP_STALE_MS });
}

export function useTeams(enabled: boolean): UseQueryResult<TeamOption[]> {
  return useQuery({ queryKey: assetKeys.teams(), queryFn: fetchTeams, enabled, staleTime: LOOKUP_STALE_MS });
}

export function useFilterableFields(categoryId: string): UseQueryResult<CustomFieldDefinition[]> {
  return useQuery({
    queryKey: assetKeys.customFields(categoryId),
    queryFn: () => fetchFilterableFields(categoryId),
    enabled: categoryId !== "",
    staleTime: LOOKUP_STALE_MS,
  });
}
