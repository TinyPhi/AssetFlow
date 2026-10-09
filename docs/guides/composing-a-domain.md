<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Composing a domain template

A domain template (`config/domains/<key>.yaml`) tells AssetFlow what your organization's world looks
like, as data: which statuses an asset can have, which moves are allowed, which categories and fields
exist. Industry words belong here and nowhere in the code. This guide covers the **`assets`** section
(milestone M2.1); the maintenance sections arrive with the maintenance milestone and will extend this
guide.

Two templates ship, and both are complete examples:

| Template | File | World |
| --- | --- | --- |
| `it-assets` | `config/domains/it-assets.yaml` | tag `AST-00001`, statuses in stock / assigned / in service / in repair / retired / lost / disposed |
| `facilities` | `config/domains/facilities.yaml` | tag `FAC/000001`, statuses commissioned / in operation / on standby / out of order / decommissioned / scrapped |

An organization picks one when it is created. The template is read when the assets module is installed
(categories are copied into the database once) and on every request that needs its rules (tag format,
statuses, transitions, vocabulary). Check your file with `make config-validate` or
`assetflow config validate <file>`; an error names the exact path, for example
`assets.statuses[3].category: unknown category "gone"`, and an invalid file stops the boot.

## `assets.tag`

```yaml
tag:
  prefix: AST      # 1-10 characters, capitals and digits, starting with a letter
  separator: "-"   # empty, or one of - _ . /
  digits: 5        # 3 to 12, zero-padded; a longer number keeps all its digits
```

Tags are generated per organization from an atomic counter, so they are unique and never reused. A
category can override the prefix with its own `tag_prefix` (see below); each prefix counts on its own.

## `assets.statuses` and `initial`

```yaml
initial: in_stock
statuses:
  - { key: in_stock, label: In stock, category: available }
  - { key: retired, label: Retired, category: ended, is_final: true }
  - { key: under_maintenance, label: Under maintenance, category: unavailable, set_only_by: maintenance }
```

- `key`: lowercase letters, digits, underscores. Stored as text, never a database enum, so adding a
  status needs no migration.
- `label`: what people read. Change it freely.
- `category`: one of `available`, `in_use`, `unavailable`, `ended`. The category says what the status
  means for filters and rules (for example "all assets in use"). `ended` ends custody.
- `is_final` (default: every `ended` status): a terminal status.
- `is_assignable` (default: every status but `ended`): whether an asset may be handed out.
- `set_only_by`: a module that alone may set this status; a manual change answers
  `reserved_for_module:<module>`.
- `initial` must be one of the statuses; new assets start there.

## `assets.transitions`

Only the moves listed here are allowed. Anything else is refused with `409 asset.invalid_transition`.

```yaml
transitions:
  - { from: in_stock, to: assigned, permission: asset.assign }
  - from: in_stock
    to: retired
    permission: asset.retire
    requires_reason: true
    conditions:
      - { field: holder, operator: exists, value: false }
```

- `permission`: must be a permission some module declares (checked at boot); the caller needs it, at
  a scope covering the asset.
- `requires_reason`: the request must carry a reason; it is recorded in the audit entry.
- `conditions`: every one must hold. Structured data, never free text: a `field` (an asset field such
  as `holder`, `holder.is_set`, `status.category`, `category.code`, or `custom.<key>` for a custom
  field), an `operator` (`equals`, `not_equals`, `in`, `not_in`, `lt`, `lte`, `gt`, `gte`, `exists`)
  and a `value`. The rule "an asset cannot be retired while assigned" is exactly the `holder` /
  `exists` / `false` condition above; both shipped templates use it on every move into a final status.
- A transition must change the status and may be declared once.

## `assets.criticality`

An ordered list of level names, lowest first: `[low, medium, high, critical]` (the default) or
`[routine, important, vital]` (`facilities`). Levels must be unique. The names are your vocabulary; the
screens read them from `GET /api/v1/assets/vocabulary`.

## `assets.categories`

A tree (`parent_code` points at another category of the same list), each entry:

```yaml
categories:
  - code: laptop
    label: Laptop
    parent_code: computer           # optional; cycles are refused
    default_criticality: medium     # must be one of assets.criticality
    responsible_team_code: it_service_desk
    tag_prefix: SRV                 # optional override of assets.tag.prefix
    custom_fields:
      - { key: ram_gb, label: RAM (GB), type: number, required: true, min: 1, max: 4096 }
      - { key: os, label: OS, type: select, options: [Windows, macOS, Linux] }
      - { key: asset_password, label: Local admin password, type: text, is_encrypted: true }
```

Custom fields have one of seven `type`s: `text`, `number`, `date`, `boolean`, `select`,
`multi_select`, `json`. Optional rules: `required`, `min` / `max` (numbers; `min` may not exceed
`max`), `regex` (text only, must compile), `options` (needed and unique for the two choice types,
refused for others), `is_unique` (unique in the organization) and `is_encrypted`. An encrypted field
cannot be unique, is never listed or filtered, and is shown only to holders of `asset.read_sensitive`.
Field keys are unique within the template.

When the assets module is installed for an organization, the categories and fields are copied into its
database tables, once and idempotently by `code` / `key`. After that the organization's administrators
own them (`/admin/asset-categories`); editing the YAML later does not change an installed organization.

## `assets.public_scan_fields` and `public_report`

```yaml
public_scan_fields: [tag, name, category, status, owner_org_unit]
public_report: true
```

What an anonymous scan of a QR label may show, and whether the public "report a problem" form is on.
Allowed: `tag`, `name`, `category`, `model`, `manufacturer`, `status`, `criticality`, `owner_org_unit`,
`location`, or `custom.<key>` of a non-encrypted field. **Never** the holder (personal data) or an
encrypted field: the validator refuses both with a specific message. The scan itself is built in a later
milestone; the setting is validated now.

## `assets.acknowledgement`

```yaml
acknowledgement:
  required: true
  remind_after_hours: 24
  escalate_after_hours: 72     # must be greater than remind_after_hours
  auto_close_after_days: 7     # optional
```

How custody confirmations behave once custody exists. Values must be positive.

## Behavior rules

```yaml
owner_follows_holder: true       # the asset's owner org unit follows the holder's unit
cascade_on_member_move: ask      # on | off | ask
```

`owner_follows_holder` and `cascade_on_member_move` (what happens to a member's held assets when the
member moves to another org unit; `ask` leaves the choice to the person doing the move) take effect with
custody. Write `on` or `off` in quotes if your YAML tooling reads them as booleans; both spellings are
accepted.

## Starting a new template

1. Copy the closer shipped template and change `domain_key` and the `modules` list as needed.
2. Rename statuses and categories; keep at least one `ended` status and its `holder` condition.
3. `make config-validate` until it is clean.
4. Create an organization with the new `domain_key`; install the assets module; open `/assets/new` and
   check the tag, the statuses and the category fields behave as intended.
