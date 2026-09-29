// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Minimal translation lookup for the Phase 2 placeholder. All UI text goes through t() (§C1.7);
// keys live in locales/en.json. A full i18n library replaces this when features land.
import en from "./locales/en.json";

type Leaves<T, P extends string = ""> = {
  [K in keyof T & string]: T[K] extends string ? `${P}${K}` : Leaves<T[K], `${P}${K}.`>;
}[keyof T & string];

export type TranslationKey = Leaves<typeof en>;

export function t(key: TranslationKey): string {
  let node: unknown = en;
  for (const part of key.split(".")) {
    node = typeof node === "object" && node !== null ? new Map(Object.entries(node)).get(part) : undefined;
  }
  return typeof node === "string" ? node : key;
}
