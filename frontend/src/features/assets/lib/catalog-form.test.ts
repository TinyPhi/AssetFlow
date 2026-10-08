// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { describe, expect, it } from "vitest";
import { ProblemError } from "@/lib/api";
import { t } from "@/lib/i18n";
import type { CategoryRecord } from "../types";
import {
  catalogFailure,
  categoryCreateBody,
  categoryErrors,
  categoryUpdateBody,
  categoryValues,
  EMPTY_CATEGORY,
  EMPTY_FIELD,
  fieldCreateBody,
  fieldErrors,
  fieldUpdateBody,
  moveTargets,
  optionsFromText,
} from "./catalog-form";

const category = (over: Partial<CategoryRecord> & { id: string; path: string }): CategoryRecord => ({
  name: over.id,
  parent_id: null,
  code: over.id,
  tag_prefix: null,
  default_criticality: null,
  responsible_team_id: null,
  status: "active",
  version: 1,
  ...over,
});

describe("category forms", () => {
  it("checks code, name and tag prefix", () => {
    expect(Object.keys(categoryErrors(EMPTY_CATEGORY, "create")).sort()).toEqual(["code", "name"]);
    expect(
      categoryErrors({ ...EMPTY_CATEGORY, code: "bad code", name: "n", tag_prefix: "ab" }, "create"),
    ).toEqual({
      code: t("assets.categories.errors.code"),
      tag_prefix: t("assets.categories.errors.tag_prefix"),
    });
    expect(categoryErrors({ ...EMPTY_CATEGORY, name: "n" }, "edit")).toEqual({});
  });

  it("builds a create body without empty optional parts", () => {
    expect(categoryCreateBody({ ...EMPTY_CATEGORY, code: " pumps ", name: " Pumps " })).toEqual({
      code: "pumps",
      name: "Pumps",
    });
    expect(
      categoryCreateBody({
        code: "p",
        name: "P",
        parent_id: "x",
        tag_prefix: "PMP",
        default_criticality: "high",
      }),
    ).toEqual({ code: "p", name: "P", parent_id: "x", tag_prefix: "PMP", default_criticality: "high" });
  });

  it("builds an edit body with clear flags for emptied settings", () => {
    const current = category({
      id: "c",
      path: "c",
      tag_prefix: "OLD",
      default_criticality: "high",
      version: 7,
    });
    const initial = categoryValues(current);
    expect(
      categoryUpdateBody(
        initial,
        { ...initial, name: "Renamed", tag_prefix: "", default_criticality: "low" },
        7,
      ),
    ).toEqual({ version: 7, name: "Renamed", clear_tag_prefix: true, default_criticality: "low" });
  });

  it("offers as move targets neither the category itself nor its descendants nor archived ones", () => {
    const nodes = [
      category({ id: "a", path: "a" }),
      category({ id: "b", path: "a.b" }),
      category({ id: "c", path: "a.b.c" }),
      category({ id: "d", path: "d" }),
      category({ id: "e", path: "e", status: "archived" }),
    ];
    const ids = moveTargets(nodes, nodes[1] ?? category({ id: "x", path: "x" })).map((n) => n.id);
    expect(ids).toEqual(["a", "d"]);
  });
});

describe("custom field forms", () => {
  it("checks key, label, options, bounds, pattern and uniqueness of an encrypted field", () => {
    expect(Object.keys(fieldErrors(EMPTY_FIELD, "create")).sort()).toEqual(["key", "label"]);
    expect(fieldErrors({ ...EMPTY_FIELD, key: "k", label: "L", field_type: "select" }, "create")).toEqual({
      optionsText: t("assets.categories.errors.options"),
    });
    expect(
      fieldErrors(
        { ...EMPTY_FIELD, key: "k", label: "L", field_type: "number", min: "5", max: "1" },
        "create",
      ),
    ).toEqual({ max: t("assets.categories.errors.range") });
    expect(fieldErrors({ ...EMPTY_FIELD, key: "k", label: "L", regex: "(" }, "create")).toEqual({
      regex: t("assets.categories.errors.regex"),
    });
    expect(
      fieldErrors({ ...EMPTY_FIELD, key: "k", label: "L", is_unique: true, is_encrypted: true }, "create"),
    ).toEqual({ is_unique: t("assets.categories.errors.unique_encrypted") });
  });

  it("does not ask for the key on edit", () => {
    expect(fieldErrors({ ...EMPTY_FIELD, label: "L" }, "edit")).toEqual({});
  });

  it("reads options one per line, trimmed and without duplicates", () => {
    expect(optionsFromText(" a \n\nb\na\n")).toEqual(["a", "b"]);
  });

  it("builds a create body with only the rules that apply to the type", () => {
    expect(
      fieldCreateBody({
        ...EMPTY_FIELD,
        key: "serial",
        label: "Serial",
        min: "3",
        max: "9",
        regex: "[A-Z]+",
      }),
    ).toEqual({
      key: "serial",
      label: "Serial",
      field_type: "text",
      is_required: false,
      is_unique: false,
      is_encrypted: false,
      position: 0,
      min: 3,
      max: 9,
      regex: "[A-Z]+",
    });
    expect(
      fieldCreateBody({
        ...EMPTY_FIELD,
        key: "tier",
        label: "Tier",
        field_type: "select",
        optionsText: "a\nb",
        min: "1",
      }),
    ).toMatchObject({ options: ["a", "b"] });
  });

  it("builds an edit body with only what changed", () => {
    const initial = { ...EMPTY_FIELD, key: "k", label: "Old", min: "2", regex: "x" };
    expect(
      fieldUpdateBody(initial, { ...initial, label: "New", min: "", regex: "", is_required: true }, 4),
    ).toEqual({ version: 4, label: "New", is_required: true, clear_min: true, clear_regex: true });
  });
});

describe("catalog failures", () => {
  it("names a version conflict, shows an API blocker, and falls back", () => {
    const conflict = new ProblemError({
      code: "asset_category.version_conflict",
      status: 409,
      detail: "stale",
    });
    expect(catalogFailure(conflict)).toBe(t("assets.categories.conflict"));
    const blocked = new ProblemError({
      code: "asset_category.archive_blocked",
      status: 409,
      detail: "3 assets still use this category.",
    });
    expect(catalogFailure(blocked)).toBe("3 assets still use this category.");
    expect(catalogFailure(new Error("x"))).toBe(t("assets.categories.save_failed"));
  });
});
