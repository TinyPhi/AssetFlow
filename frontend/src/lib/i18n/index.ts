// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Typed translation lookup and interpolation (§C1.6, §C4.9).
// All UI text goes through t(); keys live in locales/en.json.
import en from "./locales/en.json";

export * from "./format";
export * from "./useFormat";

type Leaves<T, P extends string = ""> = {
  [K in keyof T & string]: T[K] extends string ? `${P}${K}` : Leaves<T[K], `${P}${K}.`>;
}[keyof T & string];

export type TranslationKey = Leaves<typeof en>;

export type InterpolationParams = Record<string, string | number>;

let currentLocale = "en";

export function setLocale(locale: string): void {
  currentLocale = locale;
}

export function getLocale(): string {
  return currentLocale;
}

export function t(key: TranslationKey, params?: InterpolationParams): string {
  let node: unknown = en;
  for (const part of key.split(".")) {
    node = typeof node === "object" && node !== null ? new Map(Object.entries(node)).get(part) : undefined;
  }
  let text = typeof node === "string" ? node : key;

  if (params !== undefined) {
    for (const [k, v] of Object.entries(params)) {
      text = text.replaceAll(`{${k}}`, String(v));
    }
  }

  return text;
}
