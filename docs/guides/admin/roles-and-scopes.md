<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Roles and scopes

How access is granted inside an organization, once a member already exists. For how a member is
created in the first place, see [member provisioning](member-provisioning.md); for the mechanics
behind the boundary itself, see [the tenancy and scopes spec](../../specs/tenancy-and-scopes.md).

## Roles

Six fixed default roles, each a set of permissions in `<entity>.<action>` form:

| Role | Covers |
| --- | --- |
| `admin` | everything in the organization (`*`) — never platform-level actions |
| `asset_manager` | assets, QR codes, locations, plus read access to units/teams/members |
| `planner` | maintenance plans and schedules, creating/dispatching work orders |
| `team_lead` | work orders end to end, read access to assets/locations/teams/members |
| `technician` | executing and reading work orders, reading assets/locations |
| `member` | reading and acknowledging assets, raising work requests |

A role is granted at a **scope**: `organization` (everywhere), `org_unit` (that unit and its
sub-units), `team` (that team), or `self` (automatic for `self`-scope permissions — no explicit
grant needed; it's always true for the member's own resources).

## Granting and revoking

`POST /api/v1/role-grants` (create), `DELETE /api/v1/role-grants/{grant_id}` (revoke),
`GET /api/v1/role-grants` (list a member's grants).

A grant has a `role_key`, a `scope_type`, and (for `org_unit`/`team` scope) a `scope_id`. The
granter can only give out a role whose **every** permission they themselves already hold at a
scope that covers the grant's target — checked permission by permission against the granter's own
grants, not just "does the granter have some admin-ish role". Revoking requires the same standing
as granting it in the first place. Both actions are writes: a denial answers `403`, not `404`
(listing someone else's grants, a read, still answers `404` on denial — see the tenancy spec for
why reads and writes differ here).

A grant can carry an `expires_at`; an expired grant stops counting immediately (checked on every
evaluation, not swept by a background job) — see `RoleGrant.is_expired` /
`RoleGrant.grants_permission`.

## Effective access, every request

There is no grant cache to invalidate: a member's effective grants are loaded fresh from
`role_grants` on every request. A revoke or a new grant applies on the member's very next request,
not after some cache window elapses. The same is true of suspension — suspending a member or their
organization takes effect immediately, and is reported as the request's target being out of scope
(`404`) rather than as an authentication failure, so it can't be told apart from "this doesn't
exist" by an outside observer.

## Checking what a role can actually do

`can_grant()` and the scope resolver both work off the same source of truth
(`app.core.permissions.ROLE_PERMISSIONS`), so "can member X grant role Y at scope Z" and "does a
member holding role Y at scope Z actually get permission P" never disagree with each other by
construction — there's one permission table, not two implementations of the same question.
