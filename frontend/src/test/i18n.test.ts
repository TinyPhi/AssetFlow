// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Every translation key a component asks for must exist in en.json, and en.json must not keep keys
// nothing uses (§C1.7). Keys are read from the source: `t("a.b")` calls and `titleKey`/`labelKey` fields.
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import en from "@/lib/i18n/locales/en.json";

const SRC = path.resolve(__dirname, "..");
const KEY_USE = /(?:\bt\(|(?:titleKey|labelKey)[:=]\s*)\s*["']([a-z_]+(?:\.[a-z_]+)+)["']/g;

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sources(full);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [full] : [];
  });
}

function leaves(node: unknown, prefix = ""): string[] {
  if (typeof node === "string") return [prefix];
  if (typeof node !== "object" || node === null) return [];
  return Object.entries(node).flatMap(([key, value]) =>
    leaves(value, prefix === "" ? key : `${prefix}.${key}`),
  );
}

const DEFINED = new Set(leaves(en));
const USED = new Set(
  sources(SRC).flatMap((file) =>
    [...readFileSync(file, "utf8").matchAll(KEY_USE)].map((match) => match[1] ?? ""),
  ),
);

describe("en.json", () => {
  it("defines every key the source asks for", () => {
    expect([...USED].filter((key) => !DEFINED.has(key))).toEqual([]);
  });

  it("holds no key that nothing uses", () => {
    // Keys reached through a table (the theme options, the page titles) are listed here on purpose.
    const reached = new Set(["theme.light", "theme.dark", "theme.system"]);
    expect([...DEFINED].filter((key) => !USED.has(key) && !reached.has(key))).toEqual([]);
  });

  it("finds the keys the navigation declares", () => {
    expect(USED.has("nav.teams")).toBe(true);
  });
});
