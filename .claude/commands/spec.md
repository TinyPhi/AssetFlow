---
description: Interview the lead engineer one question at a time and write a feature spec to docs/specs/<name>.md following §C6.6
argument-hint: "<feature-kebab-name> [issue number]"
---

Write a feature spec for `$ARGUMENTS`. Specs are docs: this command edits only `docs/specs/<feature-kebab>.md`.

## Before asking anything

1. Read what already exists: `docs/specs/`, `docs/decisions/`, the tracker rows in `docs/tracker/roadmap-tracker.md`,
   the plan sections for the feature (grep `../Plan/OpenSource.AssetFlow.md` when present), and the code it touches.
2. Write down the **Findings** you can measure yourself (current tables, routes, file paths, counts). Do not ask
   questions the repository already answers.

## Interview

Ask **one question per message**, wait for the answer, then ask the next. Offer a recommended answer with each question
(from the plan or existing patterns) so the lead engineer can reply "yes". Stop asking when every section below is filled.
Order:

1. Goal: what outcome, for which role? Non-goals?
2. Data: new tables/columns? Which are tenant tables? Scope anchor for each record (`owner_org_unit_path`, `team_id`, holder/assignee)?
3. API: endpoints and the permission for each (`<entity>.<action>`)? Public routes (need a rate limit)?
4. Events: which domain events, who subscribes, what must be idempotent?
5. Config: new keys, defaults, what fails validation?
6. UI: screens, empty/error states, who sees which action?
7. Security: personal data involved? Outbound calls (which provider/channel, which hosts)? Abuse cases? ASVS 5.0 ids?
8. Verification: what acceptance steps prove it works?
9. Rollout: migration steps (expand -> migrate -> contract), flags, compatibility?

## Write the spec

File `docs/specs/<feature-kebab>.md`, sentence-case headings, one H1, US English, §C1 nomenclature, Mermaid for diagrams:

```markdown
# <Feature name>

| Status | Issue | Author | Reviewers |
| draft | #<n> | <role or handle> | security reviewer, maintainer |

## Goal and non-goals
## Findings
## Design
### Data            (tables, columns, indexes, RLS per §C4.8; views security_invoker)
### API             (method, path, permission, errors <area>.<reason>, pagination, version)
### Events          (<entity>.<what_happened>, payload, subscribers)
### Config          (key, default, validation)
### UI              (screens, four list states, i18n keys)
## Security
Tenancy and scope · permissions · inputs · outbound calls · personal data (DPDP/GDPR) · abuse cases · ASVS ids
## Verification
Tests to add (unit, integration, isolation, scope, authz matrix, contract, API E2E) and acceptance steps with commands.
## Rollout
Migrations, compatibility, flags, upgrade notes.
## Change log
```

Rules:
- Placeholders only for secrets (`<your-smtp-password>`); `example.org` emails; no real personal data.
- Domain words (railway, IT, facilities) belong in `config/domains/`, not in the core design.
- If the design needs a new ADR, say so under Design; do not write in `docs/decisions/` (off-limits to the agent).

When done, show the file path and suggest `/spec-review docs/specs/<feature-kebab>.md`.
