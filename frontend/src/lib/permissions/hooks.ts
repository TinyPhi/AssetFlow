// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiFetch, queryKeys } from "@/lib/api";
import { can, hasModule } from "./access";
import type { Me, ModuleKey, ScopedRecord } from "./types";

/** The signed-in member: identity, effective permissions and installed modules. */
export function useMe(enabled = true): UseQueryResult<Me> {
  return useQuery({
    queryKey: queryKeys.me(),
    queryFn: () => apiFetch<Me>("/me"),
    enabled,
    staleTime: 60_000,
  });
}

/** Whether the member holds `permission` (and, with a record, at a scope that covers it). */
export function usePermission(permission: string, record?: ScopedRecord): boolean {
  const { data } = useMe();
  return can(data, permission, record);
}

export function useInstalledModules(): ModuleKey[] {
  const { data } = useMe();
  return data?.installed_modules ?? [];
}

export function useHasModule(module: ModuleKey): boolean {
  const { data } = useMe();
  return hasModule(data, module);
}
