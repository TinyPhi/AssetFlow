// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import {
  assetKeys,
  createSavedView,
  deleteSavedView,
  fetchSavedViews,
  renameSavedView,
  type SavedViewInput,
} from "../api/assets";
import type { SavedView } from "../types";

/** The signed-in member's own saved views (the API returns only theirs). */
export function useSavedViews(): UseQueryResult<SavedView[]> {
  return useQuery({ queryKey: assetKeys.views(), queryFn: fetchSavedViews, staleTime: 30_000 });
}

export function useCreateSavedView(): UseMutationResult<SavedView, Error, SavedViewInput> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: createSavedView,
    onSuccess: () => client.invalidateQueries({ queryKey: assetKeys.views() }),
  });
}

export function useRenameSavedView(): UseMutationResult<SavedView, Error, { view: SavedView; name: string }> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ view, name }) => renameSavedView(view, name),
    onSuccess: () => client.invalidateQueries({ queryKey: assetKeys.views() }),
  });
}

export function useDeleteSavedView(): UseMutationResult<void, Error, string> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: deleteSavedView,
    onSuccess: () => client.invalidateQueries({ queryKey: assetKeys.views() }),
  });
}
