// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { describe, expect, it } from "vitest";
import { t } from "@/lib/i18n";
import type { CustomFieldDefinition } from "../types";
import { parseCustomFieldValues, toFieldValue } from "./custom-field-schema";

function def(
  over: Partial<CustomFieldDefinition> & { key: string; field_type: string },
): CustomFieldDefinition {
  return {
    id: `id-${over.key}`,
    label: over.key,
    is_encrypted: false,
    status: "active",
    is_required: false,
    is_unique: false,
    position: 0,
    version: 1,
    rules: { min: null, max: null, regex: null, options: [] },
    ...over,
  };
}

const ok = (defs: CustomFieldDefinition[], values: Record<string, string | string[]>): unknown => {
  const result = parseCustomFieldValues(defs, values);
  if (!result.ok) throw new Error(JSON.stringify(result.errors));
  return result.data;
};

const errors = (defs: CustomFieldDefinition[], values: Record<string, string | string[]>) => {
  const result = parseCustomFieldValues(defs, values);
  return result.ok ? {} : result.errors;
};

describe("custom field schema built from definitions", () => {
  it("text: required, length bounds and a regex", () => {
    const field = def({
      key: "code",
      field_type: "text",
      is_required: true,
      rules: { min: 2, max: 5, regex: "[A-Z]+", options: [] },
    });
    expect(errors([field], { code: "" })).toEqual({ code: t("assets.form.errors.required") });
    expect(errors([field], { code: "A" })).toEqual({ code: t("assets.form.errors.min_length", { min: 2 }) });
    expect(errors([field], { code: "ABCDEF" })).toEqual({
      code: t("assets.form.errors.max_length", { max: 5 }),
    });
    expect(errors([field], { code: "ab" })).toEqual({ code: t("assets.form.errors.pattern") });
    expect(ok([field], { code: "AB" })).toEqual({ code: "AB" });
  });

  it("number: typed value with min and max", () => {
    const field = def({
      key: "power",
      field_type: "number",
      rules: { min: 0, max: 10, regex: null, options: [] },
    });
    expect(ok([field], { power: "7.5" })).toEqual({ power: 7.5 });
    expect(errors([field], { power: "abc" })).toEqual({ power: t("assets.form.errors.number") });
    expect(errors([field], { power: "-1" })).toEqual({
      power: t("assets.form.errors.min_number", { min: 0 }),
    });
    expect(errors([field], { power: "11" })).toEqual({
      power: t("assets.form.errors.max_number", { max: 10 }),
    });
  });

  it("date: a real calendar date only", () => {
    const field = def({ key: "installed", field_type: "date" });
    expect(ok([field], { installed: "2026-02-28" })).toEqual({ installed: "2026-02-28" });
    expect(errors([field], { installed: "2026-02-30" })).toEqual({ installed: t("assets.form.errors.date") });
    expect(errors([field], { installed: "28/02/2026" })).toEqual({ installed: t("assets.form.errors.date") });
  });

  it("boolean: true or false, nothing when optional and empty", () => {
    const field = def({ key: "certified", field_type: "boolean" });
    expect(ok([field], { certified: "false" })).toEqual({ certified: false });
    expect(ok([field], { certified: "" })).toEqual({});
  });

  it("select: one of the options", () => {
    const field = def({
      key: "tier",
      field_type: "select",
      rules: { min: null, max: null, regex: null, options: ["a", "b"] },
    });
    expect(ok([field], { tier: "b" })).toEqual({ tier: "b" });
    expect(errors([field], { tier: "c" })).toEqual({ tier: t("assets.form.errors.option") });
  });

  it("multi-select: a list inside the options; required needs one", () => {
    const field = def({
      key: "tags",
      field_type: "multi_select",
      is_required: true,
      rules: { min: null, max: null, regex: null, options: ["x", "y"] },
    });
    expect(ok([field], { tags: ["x", "y"] })).toEqual({ tags: ["x", "y"] });
    expect(errors([field], { tags: [] })).toEqual({ tags: t("assets.form.errors.required") });
    expect(errors([field], { tags: ["z"] })).toEqual({ tags: t("assets.form.errors.option") });
  });

  it("json: parsed, refused when invalid or too large", () => {
    const field = def({ key: "extra", field_type: "json" });
    expect(ok([field], { extra: '{"a": [1, 2]}' })).toEqual({ extra: { a: [1, 2] } });
    expect(errors([field], { extra: "{oops" })).toEqual({ extra: t("assets.form.errors.json") });
    expect(errors([field], { extra: JSON.stringify("x".repeat(17_000)) })).toEqual({
      extra: t("assets.form.errors.json_too_large"),
    });
  });

  it("reports one message per failing key and leaves out empty optional fields", () => {
    const defs = [
      def({ key: "a", field_type: "text", is_required: true }),
      def({ key: "b", field_type: "number" }),
      def({ key: "c", field_type: "text" }),
    ];
    expect(errors(defs, { a: "", b: "x" })).toEqual({
      a: t("assets.form.errors.required"),
      b: t("assets.form.errors.number"),
    });
    expect(ok(defs, { a: "v", b: "", c: "" })).toEqual({ a: "v" });
  });

  it("turns stored values into the text a form shows", () => {
    expect(toFieldValue(def({ key: "n", field_type: "number" }), 4)).toBe("4");
    expect(toFieldValue(def({ key: "m", field_type: "multi_select" }), ["x"])).toEqual(["x"]);
    expect(toFieldValue(def({ key: "j", field_type: "json" }), { a: 1 })).toBe('{\n  "a": 1\n}');
    expect(toFieldValue(def({ key: "t", field_type: "text" }), null)).toBe("");
  });
});
