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
  attachComponent,
  changeStatus,
  createAsset,
  detachComponent,
  fetchAsset,
  fetchComponents,
  fetchTransitions,
  fetchVocabulary,
  updateAsset,
  type ChangeStatusInput,
  type CreateAssetBody,
  type UpdateAssetBody,
} from "../api/asset-detail";
import { assetKeys } from "../api/assets";
import type { AssetDetail, ComponentChild, Transition, Vocabulary } from "../types";

const LOOKUP_STALE_MS = 5 * 60_000;

/** One asset. Encrypted values the API returns live only in this query's data, which is dropped on unmount. */
export function useAsset(id: string): UseQueryResult<AssetDetail> {
  return useQuery({
    queryKey: assetKeys.detail(id),
    queryFn: ({ signal }) => fetchAsset(id, signal),
    gcTime: 0,
  });
}

/** The template's status labels and criticality levels; the screens fall back to readable keys without it. */
export function useVocabulary(): UseQueryResult<Vocabulary> {
  return useQuery({ queryKey: assetKeys.vocabulary(), queryFn: fetchVocabulary, staleTime: LOOKUP_STALE_MS });
}

export function useTransitions(id: string, version: number): UseQueryResult<Transition[]> {
  return useQuery({
    queryKey: [...assetKeys.transitions(id), version],
    queryFn: () => fetchTransitions(id),
  });
}

export function useComponents(id: string): UseQueryResult<ComponentChild[]> {
  return useQuery({ queryKey: assetKeys.components(id), queryFn: () => fetchComponents(id) });
}

export function useCreateAsset(): UseMutationResult<
  AssetDetail,
  Error,
  { body: CreateAssetBody; idempotencyKey: string }
> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ body, idempotencyKey }) => createAsset(body, idempotencyKey),
    gcTime: 0,
    onSuccess: () => client.invalidateQueries({ queryKey: assetKeys.lists() }),
  });
}

/** After a write, the detail is replaced by the response and the lists are marked stale. */
function useAfterWrite(): (asset: AssetDetail) => Promise<void> {
  const client = useQueryClient();
  return async (asset) => {
    client.setQueryData(assetKeys.detail(asset.id), asset);
    await client.invalidateQueries({ queryKey: assetKeys.lists() });
  };
}

export function useUpdateAsset(id: string): UseMutationResult<AssetDetail, Error, UpdateAssetBody> {
  const afterWrite = useAfterWrite();
  // `gcTime: 0`: the mutation's variables and result may hold encrypted values; the cache drops them as
  // soon as the form lets go of the mutation.
  return useMutation({ mutationFn: (body) => updateAsset(id, body), onSuccess: afterWrite, gcTime: 0 });
}

export function useChangeStatus(id: string): UseMutationResult<AssetDetail, Error, ChangeStatusInput> {
  const afterWrite = useAfterWrite();
  return useMutation({ mutationFn: (input) => changeStatus(id, input), onSuccess: afterWrite, gcTime: 0 });
}

/** Attach and detach move the parent's version, so the detail is read again as well as the components. */
function useAfterComponentChange(id: string): () => Promise<void> {
  const client = useQueryClient();
  return async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: assetKeys.detail(id) }),
      client.invalidateQueries({ queryKey: assetKeys.lists() }),
    ]);
  };
}

export function useAttachComponent(
  id: string,
): UseMutationResult<void, Error, { childId: string; version: number }> {
  const after = useAfterComponentChange(id);
  return useMutation({
    mutationFn: ({ childId, version }) => attachComponent(id, childId, version),
    onSuccess: after,
  });
}

export function useDetachComponent(
  id: string,
): UseMutationResult<void, Error, { childId: string; version: number }> {
  const after = useAfterComponentChange(id);
  return useMutation({
    mutationFn: ({ childId, version }) => detachComponent(id, childId, version),
    onSuccess: after,
  });
}
