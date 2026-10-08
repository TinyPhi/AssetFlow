// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { describe, expect, it } from "vitest";
import { makeMe } from "@/test/server";
import { can, hasModule } from "./access";
import type { GrantedPermission, PermissionScope } from "./types";

function held(permission: string, ...scopes: PermissionScope[]): GrantedPermission {
  return { permission, scopes };
}
const ORG: PermissionScope = { scope_type: "organization", scope_id: null };

describe("can", () => {
  it("is false for a missing profile and for a permission not held", () => {
    expect(can(undefined, "team.read")).toBe(false);
    expect(can(makeMe(), "team.read")).toBe(false);
  });

  it("is true for a held permission when no record is given, at any scope", () => {
    const me = makeMe({ permissions: [held("team.read", { scope_type: "team", scope_id: "t1" })] });
    expect(can(me, "team.read")).toBe(true);
  });

  it("is false for everything when the member is suspended", () => {
    const me = makeMe({ is_suspended: true, permissions: [held("team.read", ORG)] });
    expect(can(me, "team.read")).toBe(false);
  });

  it("lets organization scope cover any record", () => {
    const me = makeMe({ permissions: [held("asset.update", ORG)] });
    expect(can(me, "asset.update", { orgUnitId: "u9", teamId: "t9" })).toBe(true);
    expect(can(me, "asset.update", {})).toBe(true);
  });

  it("covers a record only when a scope matches it", () => {
    const me = makeMe({
      permissions: [
        held(
          "asset.update",
          { scope_type: "org_unit", scope_id: "u1" },
          { scope_type: "team", scope_id: "t1" },
          { scope_type: "self", scope_id: null },
        ),
      ],
    });
    expect(can(me, "asset.update", { orgUnitId: "u1" })).toBe(true);
    expect(can(me, "asset.update", { orgUnitId: "u2" })).toBe(false);
    expect(can(me, "asset.update", { teamId: "t1" })).toBe(true);
    expect(can(me, "asset.update", { teamId: "t2" })).toBe(false);
    expect(can(me, "asset.update", { holderMemberId: me.member_id })).toBe(true);
    expect(can(me, "asset.update", { holderMemberId: "someone-else" })).toBe(false);
    expect(can(me, "asset.update", {})).toBe(false);
  });
});

describe("hasModule", () => {
  it("is true only for an installed module", () => {
    const me = makeMe({ installed_modules: ["assets"] });
    expect(hasModule(me, "assets")).toBe(true);
    expect(hasModule(me, "maintenance")).toBe(false);
    expect(hasModule(undefined, "assets")).toBe(false);
  });
});
