<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Organization structure: units, locations and teams

Three independent structures under `/api/v1`, each scoped to the caller's own organization.

## Org units

`POST/GET /org-units`, `GET/PATCH/PUT /org-units/{id}`, `POST /org-units/{id}/move`,
`POST /org-units/{id}/archive`.

A tree, one per organization. Each unit has a unique business `code`, a display `name`, and a
free-form `type` (e.g. `division`, `unit`, `branch` — neutral vocabulary; no industry-specific
value is baked into core code). A unit owns assets and defines access scope: a role grant at
`org_unit` scope covers that unit and every unit under it.

- **Move** (`POST /{id}/move`) re-parents a unit, recalculating its own and every descendant's
  materialized path atomically in one transaction. Moving a unit under its own descendant is
  rejected (cycle prevention).
- **Archive** (`POST /{id}/archive`) is blocked while the unit still has:
  - active child units (`blocker: active_children`),
  - active members assigned to it (`blocker: active_members`), or
  - active teams owned by it (`blocker: active_teams`).

  The response names the exact blocker so the caller knows what to resolve first, instead of a
  generic refusal.

## Locations

`POST/GET /locations`, `GET/PATCH/PUT /locations/{id}`, `POST /locations/{id}/move`,
`DELETE /locations/{id}`.

A separate tree from org units — where an asset physically sits, independent of which org unit
owns it or which team maintains it. Same move semantics as org units (atomic path recompute,
cycle prevention). Deleting a location with child sub-locations is blocked
(`blocker: child_locations`).

## Teams

`POST/GET /teams`, `GET/PATCH /teams/{id}`, `POST /teams/{id}/archive`, plus membership under
`/teams/{id}/members`.

Flat, not a tree — a team can span org units, and is the dispatch target for maintenance work. A
team may optionally be owned by one org unit (`owning_org_unit_id`); clearing that link is
explicit (`clear_owning_org_unit: true` on update, not just omitting the field, since an omitted
field already means "leave unchanged").

Team membership (`team_members`) is time-bounded: a member is added for a period, not just
present or absent, so a team's past composition stays reconstructable. Archiving a team is
blocked while it has active members (`blocker: active_members`).

## Who can do what

Every write above is checked against the caller's role grants (see
[roles and scopes](roles-and-scopes.md)): `org_unit.create` / `.update` / `.archive`,
`location.create` / `.update` / `.archive` / `.delete`, `team.create` / `.update` / `.archive`.
A denied write answers `403`; a denied read (the resource exists but is outside the caller's
scope) answers `404`, revealing nothing about what's actually there.

Every create, update, move and archive writes one audit event and one outbox row in the same
transaction as the change itself — see [the audit guide](../../specs/tenancy-and-scopes.md) for
how that boundary is enforced.

## Bulk import

For onboarding an organization's structure in one pass instead of one call per unit/team/member,
see the bulk import API (`POST /api/v1/import/preview`, `POST /api/v1/import/commit`): preview
validates every row and writes nothing; commit runs the whole file as one transaction, all or
nothing, and is idempotent on each row's business key (re-importing the same file a second time
changes nothing).
