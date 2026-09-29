# Context: configuration and domain templates

Orientation for `config/`, `core/config*`, module `config.py` files and anything that looks industry-specific. Plan sections: D8, D12, §B5.9, §B7.1–§B7.4, §B12.2, §C1.2, §C1.6 (config keys, env vars), §C4.7, §C12 (domain-terms denylist).

## The config-first rule

**If a behaviour is specific to one industry or organization, it belongs in a domain template (`config/domains/*.yaml`), never in code** (§B12.2). No industry logic lives in `backend/app/` or `frontend/src/`.

| If the change is... | It goes in... |
| --- | --- |
| Specific to one industry or organization | `config/domains/<template>.yaml` |
| A new state or transition | the template's workflow section |
| A new "when X, notify or do Y" rule | an automation rule in the template |
| A new notification destination | a channel in `backend/app/channels/` |
| A new external service | a provider in `providers/<pillar>/` (ADR) |
| A capability every organization needs | a module feature (spec first) |
| A new rule type, condition or action | an engine change (ADR first) |

If the engines cannot express what a task needs, stop and write `docs/tracker/BLOCKERS.md`; do not hardcode it.

## Sources of truth (§B7.1)

**Definitions live in files, assignments live in the database.** One thing never has two sources.

| What | Where |
| --- | --- |
| Platform settings, providers, rate limits, platform admins | `config/assetflow.yaml` (restart to apply) |
| Roles/permissions, statuses, workflows, priorities, SLAs, automations, templates | `assetflow.yaml`, `config/domains/*.yaml`, `config/templates/` |
| Installed modules and chosen template | `organization_modules`, `organizations.domain_key` |
| Org units, teams, members, locations, grants, channel installations, per-org settings | database |

## Platform config (`config/assetflow.yaml`, §B7.2)

Sections: `platform`, `database`, `providers.{auth,secrets,telemetry,events}`, `notifications.channels`, `security.rate_limits` (100/min general, 10/min sign-in, 10/min public scan, 5/hour public report), `modules`, `rbac` (baseline + roles `viewer`, `technician`, `team_lead`, `asset_manager`, `maintenance_planner`, `org_unit_manager`, `admin`), `domains` (`it-assets` default, `rail-maintenance`, `facilities`). **Never secret values**: only `secret://...` references and `${ASSETFLOW_*}`.

## Domain template sections (§B7.3)

`vocabulary`, `organization` (org unit/location/team types, provisioning policy), `assets.tag`, `assets.statuses` (each with a category), `assets.categories`, `assets.public_scan_fields`, `assets.public_report`, `assets.acknowledgement`, `maintenance.work_order_types`, `maintenance.priorities`, `maintenance.priority_matrix`, `maintenance.sla`, `maintenance.work_order_workflow`, `maintenance.escalation`, `maintenance.routing_rules`, `automations`.

Conditions are structured (`field`, operator, value), never free text (D8).

## Modules and templates (§B5.9)

- Modules: `assets`, `maintenance` (maintenance requires assets). An organization admin installs one with `module.install` and picks a template; until then its routes return `module.not_installed`.
- Uninstall hides the module and keeps data. Install/uninstall are audited.

## Neutral vocabulary (D12, §C1.2)

- Code, DB, API and config keys use neutral terms: `organization`, `org_unit`, `team`, `member`, `location`, `asset`, `work_request`, `work_order`. Organizations change **display labels only** through `vocabulary`.
- `scripts/check-domain-terms.sh` fails on denylisted words in `backend/app/` and `frontend/src/` (industry words like rail, depot, laptop; company and gateway names; `employee`, `department`). They may appear only in domain templates, notification templates, translation files and docs examples.

## Validation (§B7.4)

- Pydantic validates all config at boot; invalid config **stops boot** with the exact path (`maintenance.priority_matrix.map[1][2]: unknown priority "p5"`).
- `assetflow config validate <file>` / `make config-validate` run in CI.
- Cross-references: every `rbac` permission exists in a module's `permissions.py`; every workflow state is declared; every template and channel exists; every condition field is registered for its event; every `domain_key` exists; no zero/negative SLA durations; no automations sending to unconfigured destinations.
- Applied config is audited as `config.applied` with a hash.

## Code access (§C4.7)

- Read `assetflow.core.config.settings` (platform) and `ctx.domain` (organization's template). Never `os.environ` outside `core/config.py`.
- New key: snake_case, nested by area (`notifications.channels.email.default_from`); Pydantic field with a description; default or a clear validation error; appears in generated `docs/reference/config.md`.
- Status values are text validated against the template, not enums.
