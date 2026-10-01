// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Theme-regression source scan (§B10): components use semantic tokens only.
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SRC = path.resolve(__dirname, "..");
const PALETTE =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|white|black";
const RAW_PALETTE = new RegExp(
  String.raw`\b(?:bg|text|border|ring|fill|stroke|from|to|via|outline)-(?:${PALETTE})(?:-\d{2,3})?\b`,
);
const HEX = /#[0-9a-fA-F]{3,8}\b/;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.(tsx?|css)$/.test(entry.name) && !entry.name.endsWith(".test.ts") ? [full] : [];
  });
}

describe("theme regression", () => {
  it("has no raw palette classes or hex colors outside tokens.css", () => {
    const offenders = sourceFiles(SRC)
      .filter((file) => path.basename(file) !== "tokens.css")
      .filter((file) => {
        const text = readFileSync(file, "utf8");
        return RAW_PALETTE.test(text) || HEX.test(text);
      })
      .map((file) => path.relative(SRC, file));
    expect(offenders).toEqual([]);
  });
});
