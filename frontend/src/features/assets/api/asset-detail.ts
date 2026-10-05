// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// The asset detail, create, edit, status and component service functions over `lib/api` (§C4.9).
// Hooks call these; components never call `fetch`.
import { apiFetch } from "@/lib/api";
import type { AssetDetail, ComponentChild, Transition, Vocabulary } from "../types";
import { parseAssetDetail, parseComponents, parseTransitions, parseVocabulary } from "./detail-parsers";

export async function fetchAsset(id: string, signal?: AbortSignal): Promise<AssetDetail> {
  const data = await apiFetch<unknown>(`/assets/${id}`, signal === undefined ? {} : { signal });
  return parseAssetDetail(data);
}

/** The create body: the core fields plus `custom_fields` (encrypted values travel in the same object). */
export type CreateAssetBody = Record<string, unknown>;

export async function createAsset(body: CreateAssetBody, idempotencyKey: string): Promise<AssetDetail> {
  const data = await apiFetch<unknown>("/assets", { method: "POST", body, idempotencyKey });
  return parseAssetDetail(data);
}

/** The edit body: only changed fields, `clear_*` flags, and the `version` being edited. */
export type UpdateAssetBody = Record<string, unknown> & { version: number };

export async function updateAsset(id: string, body: UpdateAssetBody): Promise<AssetDetail> {
  return parseAssetDetail(await apiFetch<unknown>(`/assets/${id}`, { method: "PATCH", body }));
}

export async function fetchTransitions(id: string): Promise<Transition[]> {
  return parseTransitions(await apiFetch<unknown>(`/assets/${id}/transitions`));
}

export interface ChangeStatusInput {
  to_status: string;
  version: number;
  reason?: string;
}

export async function changeStatus(id: string, input: ChangeStatusInput): Promise<AssetDetail> {
  const data = await apiFetch<unknown>(`/assets/${id}/change-status`, { method: "POST", body: input });
  return parseAssetDetail(data);
}

export async function fetchComponents(id: string): Promise<ComponentChild[]> {
  return parseComponents(await apiFetch<unknown>(`/assets/${id}/components`));
}

export async function attachComponent(parentId: string, childId: string, version: number): Promise<void> {
  await apiFetch<unknown>(`/assets/${parentId}/components`, {
    method: "POST",
    body: { child_asset_id: childId, version },
  });
}

export async function detachComponent(parentId: string, childId: string, version: number): Promise<void> {
  await apiFetch<unknown>(`/assets/${parentId}/components/${childId}/detach`, {
    method: "POST",
    body: { version },
  });
}

export async function fetchVocabulary(): Promise<Vocabulary> {
  return parseVocabulary(await apiFetch<unknown>("/assets/vocabulary"));
}
