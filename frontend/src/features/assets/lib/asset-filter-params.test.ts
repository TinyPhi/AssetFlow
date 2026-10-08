// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { describe, expect, it } from "vitest";
import {
  activeChips,
  clearFilters,
  DEFAULT_SORT,
  emptyFilters,
  hasActiveFilters,
  humanizeKey,
  nextSort,
  normalizeFilters,
  parseListState,
  removeChip,
  stateFromView,
  toApiParams,
  toSearchParams,
  toViewQuery,
} from "./asset-filter-params";

function parse(query: string): ReturnType<typeof parseListState> {
  return parseListState(new URLSearchParams(query));
}

describe("parseListState", () => {
  it("reads every filter from the query string", () => {
    const { filters, sort } = parse(
      "q=pump&status=in_service&status=repair&category_id=c1&include_subcategories=true" +
        "&owner_org_unit_id=o1&holder_type=team&holder_team_id=t1&criticality=high" +
        "&warranty_end_before=2027-01-31&cf.voltage.gte=200&sort=name",
    );
    expect(filters.q).toBe("pump");
    expect(filters.status).toEqual(["in_service", "repair"]);
    expect(filters.categoryId).toBe("c1");
    expect(filters.includeSubcategories).toBe(true);
    expect(filters.ownerOrgUnitId).toBe("o1");
    expect(filters.holderType).toBe("team");
    expect(filters.holderTeamId).toBe("t1");
    expect(filters.criticality).toEqual(["high"]);
    expect(filters.warrantyEndBefore).toBe("2027-01-31");
    expect(filters.custom).toEqual({ "cf.voltage.gte": "200" });
    expect(sort).toBe("name");
  });

  it("falls back to the default sort for an unknown key", () => {
    expect(parse("sort=password").sort).toBe(DEFAULT_SORT);
    expect(parse("sort=-name").sort).toBe("-name");
    expect(parse("").sort).toBe(DEFAULT_SORT);
  });

  it("drops an unknown holder type, a bad date and an unknown availability", () => {
    const { filters } = parse("holder_type=robot&warranty_end_after=tomorrow&status_category=weird");
    expect(filters.holderType).toBe("");
    expect(filters.warrantyEndAfter).toBe("");
    expect(filters.statusCategory).toBe("");
  });

  it("keeps a sub-tree switch only with its parent filter", () => {
    const { filters } = parse("include_subcategories=true&include_sub_units=true&include_sub_locations=true");
    expect(filters.includeSubcategories).toBe(false);
    expect(filters.includeSubUnits).toBe(false);
    expect(filters.includeSubLocations).toBe(false);
  });

  it("keeps a holder team only for the team holder type", () => {
    expect(parse("holder_type=member&holder_team_id=t1").filters.holderTeamId).toBe("");
  });

  it("keeps custom-field filters only with a category, and only well-formed names", () => {
    expect(parse("cf.voltage=220").filters.custom).toEqual({});
    expect(parse("category_id=c1&cf.voltage=220&cf.Bad-Key=1&other=2").filters.custom).toEqual({
      "cf.voltage": "220",
    });
  });
});

describe("toSearchParams and toApiParams", () => {
  it("round-trips a state through the query string", () => {
    const state = parse("q=pump&status=a&status=b&category_id=c1&include_subcategories=true&sort=-name");
    expect(parseListState(toSearchParams(state))).toEqual(state);
  });

  it("leaves out empty values and the default sort", () => {
    expect(toSearchParams({ filters: emptyFilters(), sort: DEFAULT_SORT }).toString()).toBe("");
  });

  it("trims the search text and de-duplicates multi values", () => {
    const params = toSearchParams({
      filters: { ...emptyFilters(), q: "  pump ", status: ["a", "a", " "] },
      sort: DEFAULT_SORT,
    });
    expect(params.toString()).toBe("q=pump&status=a");
  });

  it("builds a page request with the sort, the cursor and the page size", () => {
    const state = parse("q=pump");
    expect(toApiParams(state).toString()).toBe("q=pump&sort=-created_at&limit=50");
    expect(toApiParams(state, { after: "abc", limit: 25 }).toString()).toBe(
      "q=pump&sort=-created_at&after=abc&limit=25",
    );
  });
});

describe("chips", () => {
  it("lists one chip per value in force and none for the search text", () => {
    const { filters } = parse("q=x&status=a&status=b&category_id=c1&criticality=high");
    expect(activeChips(filters).map((chip) => chip.id)).toEqual([
      "status:a",
      "status:b",
      "categoryId:c1",
      "criticality:high",
    ]);
    expect(hasActiveFilters(parse("q=x").filters)).toBe(false);
  });

  it("removes one multi value and keeps the rest", () => {
    const { filters } = parse("status=a&status=b");
    const chip = activeChips(filters)[0];
    expect(chip).toBeDefined();
    if (chip === undefined) return;
    expect(removeChip(filters, chip).status).toEqual(["b"]);
  });

  it("clearing the category also clears what depends on it", () => {
    const { filters } = parse("category_id=c1&include_subcategories=true&cf.voltage=220");
    const chip = activeChips(filters).find((c) => c.field === "categoryId");
    expect(chip).toBeDefined();
    if (chip === undefined) return;
    const next = removeChip(filters, chip);
    expect(next.categoryId).toBe("");
    expect(next.includeSubcategories).toBe(false);
    expect(next.custom).toEqual({});
  });

  it("clears every filter, keeping the search text unless told otherwise", () => {
    const { filters } = parse("q=pump&status=a");
    expect(clearFilters(filters).q).toBe("pump");
    expect(clearFilters(filters).status).toEqual([]);
    expect(clearFilters(filters, false).q).toBe("");
  });
});

describe("saved views", () => {
  it("stores the filters as scalars and lists, and restores the same state", () => {
    const state = parse("q=pump&status=a&status=b&category_id=c1&include_subcategories=true&sort=name");
    const query = toViewQuery(state.filters);
    expect(query).toEqual({
      q: "pump",
      status: ["a", "b"],
      category_id: "c1",
      include_subcategories: true,
    });
    expect(stateFromView({ query, sort: state.sort })).toEqual(state);
  });

  it("never lets a stored view smuggle in an unknown sort or filter", () => {
    const state = stateFromView({ query: { owner: "x", status: ["a"] }, sort: "drop table" });
    expect(state.sort).toBe(DEFAULT_SORT);
    expect(state.filters.status).toEqual(["a"]);
  });
});

describe("small helpers", () => {
  it("makes a status key readable", () => {
    expect(humanizeKey("in_use")).toBe("In use");
    expect(humanizeKey("")).toBe("");
  });

  it("cycles a column's sort: ascending, then descending, then ascending", () => {
    expect(nextSort("-created_at", "name")).toBe("name");
    expect(nextSort("name", "name")).toBe("-name");
    expect(nextSort("-name", "name")).toBe("name");
  });

  it("normalizes an unnormalized set the same way the URL does", () => {
    const f = normalizeFilters({ ...emptyFilters(), includeSubUnits: true, holderTeamId: "t1" });
    expect(f.includeSubUnits).toBe(false);
    expect(f.holderTeamId).toBe("");
  });
});
