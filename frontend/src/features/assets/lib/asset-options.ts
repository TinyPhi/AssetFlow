// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { TranslationKey } from "@/lib/i18n";
import type { HolderType } from "../types";
import type { SortKey } from "./asset-filter-params";

// Option lists as data with a `labelKey` each, so the i18n key check sees every key in use.

export const HOLDER_TYPE_OPTIONS: readonly { value: HolderType; labelKey: TranslationKey }[] = [
  { value: "member", labelKey: "assets.holder_type.member" },
  { value: "team", labelKey: "assets.holder_type.team" },
  { value: "location", labelKey: "assets.holder_type.location" },
];

export const STATUS_CATEGORY_OPTIONS: readonly { value: string; labelKey: TranslationKey }[] = [
  { value: "available", labelKey: "assets.status_category.available" },
  { value: "in_use", labelKey: "assets.status_category.in_use" },
  { value: "unavailable", labelKey: "assets.status_category.unavailable" },
  { value: "ended", labelKey: "assets.status_category.ended" },
];

export const SORT_OPTIONS: readonly { key: SortKey; labelKey: TranslationKey }[] = [
  { key: "created_at", labelKey: "assets.sort.created_at" },
  { key: "updated_at", labelKey: "assets.sort.updated_at" },
  { key: "name", labelKey: "assets.sort.name" },
  { key: "tag", labelKey: "assets.sort.tag" },
  { key: "status", labelKey: "assets.sort.status" },
  { key: "warranty_end", labelKey: "assets.sort.warranty_end" },
  { key: "purchase_date", labelKey: "assets.sort.purchase_date" },
];

export function holderTypeLabelKey(type: HolderType): TranslationKey {
  return HOLDER_TYPE_OPTIONS.find((option) => option.value === type)?.labelKey ?? "assets.holder_type.member";
}
