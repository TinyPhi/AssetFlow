<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# The asset catalog

How to find, create and change assets, and how to set up the categories and fields they use. Written
for people who record and look after assets (the `asset_manager` role and `admin`) and for members who
only look things up. The words on screen (status names, criticality levels, categories) come from your
organization's [domain template](../composing-a-domain.md), so yours may differ from the examples.

> **Screenshots:** not yet added. They need a running stack with demo data (light theme, 1440 px); see
> the open items in the P8-12 record.

## What you can see

You see an asset when your role grant covers the **org unit that owns it**, when your **team** holds it,
or when you hold it yourself. A manager of a parent unit sees the assets of every unit below it; the
manager of a sibling unit does not see them at all. An asset outside your scope is reported as "not
found", never as "forbidden", so its existence is not revealed. Details: [roles and
scopes](../admin/roles-and-scopes.md).

Changing an asset needs the matching permission (`asset.update`, `asset.create`, `asset.retire` ...)
at a scope that covers the asset. If you hold the permission but not for that asset, the answer is
`scope.denied`; if you hold no such permission at all, it is `auth.permission_denied`.

## Find assets (`/assets`)

- **Search** is fuzzy: a misspelled name ("Latitud Workstaton") still finds "Latitude Workstation".
  It looks at tag, name, serial number and model. Type at least three characters.
- **Filters**: status, status category, category (optionally with its subcategories), owner org unit
  (optionally with sub-units), location, holder, criticality, manufacturer, supplier, warranty and
  purchase dates, and any **custom field** (`cf.<key>`; numbers and dates also take a from and a to).
  Encrypted fields cannot be searched or filtered.
- **Sort** by tag, name, status, criticality, dates; ties are always broken the same way, so pages never
  repeat or skip a row.
- **Pages** load as you scroll (cursor pages). The total is shown when asked for, capped at 10,000.
- **Columns**: choose which columns the table shows. Below 1024 px wide the table becomes cards.
- **Saved views**: save the current filters, sort and columns under a name. A view is yours alone, and
  it never widens what you may see; opening it simply re-applies the stored filters.

The four list states are all designed: loading, empty (with a reset), error (with retry), and results.

## Create an asset (`/assets/new`)

1. Pick a **category**: its custom fields appear below the common ones.
2. Fill in name and owner org unit (required) and, if you wish, model, manufacturer, supplier, serial
   number, location, criticality, purchase and warranty data, notes.
3. The **tag** is generated for you from the template's format (for example `AST-00042`); a category can
   override the prefix. Only a reserved QR tag or an import row supplies its own.
4. The first **status** is the template's initial one; the criticality defaults to the category's.

Every rule of a custom field is checked before saving and refused with a message on the field itself:
required, minimum and maximum, pattern, allowed options, type, and "unique in the organization".
Saving the same request twice (same `Idempotency-Key`) creates the asset once.

## Look at and edit an asset (`/assets/:id`)

The detail page shows the fields, the current holder, the **status** with the moves you may take now,
and the **components**. Edit in place: every save carries the record's version. If someone
changed the asset meanwhile you get a conflict dialog showing what changed, and nothing is overwritten.

### Status

Statuses and the moves between them are defined by your template, not by the software. The page lists
only the moves that are declared, that you may take on this asset, and whose conditions hold. A move that
is not allowed answers `409 asset.invalid_transition` with a sentence naming the current status, the
status you asked for and what to do. Some moves need a **reason**. Moving to an ended status (retired,
lost, disposed, scrapped) is refused while the asset has a holder: return it first. A status marked
`set_only_by: maintenance` cannot be set by hand.

### Components

An asset can have child assets (a disk in a server). Attach and detach from the parent's page; an asset
has at most one parent and a parent cannot be placed under its own child. When you change the parent's
owner org unit or location and tick **move components**, every component (and their components) moves in
the same step, each with its own audit entry. If any one of them is outside your scope, nothing moves.

### Encrypted fields

A field marked **encrypted** (for example a local admin password) is stored encrypted and never appears
in lists. On the detail page you see only "set" or "not set" unless you hold `asset.read_sensitive`,
in which case the value is shown.

## Categories, fields, manufacturers and suppliers (`/admin/asset-categories`)

Needs `asset.update` at organization scope (this data is shared by the whole organization).

- **Categories** form a tree. Move a category (cycles are refused) or archive it (refused while it has
  active children or assets; nothing is ever deleted).
- **Custom fields** belong to a category and are inherited by its subcategories. Seven types: text,
  number, date, yes/no, single choice, multiple choice, structured (JSON). Optional rules: required,
  minimum, maximum, pattern (text), options (choices), unique, encrypted. The key is fixed once created;
  the type and the encrypted flag cannot change once any asset holds a value for the field.
- **Manufacturers** and **suppliers** are simple lists, archived rather than deleted.
- Installing the assets module copies the template's categories and fields once; your later edits are
  never overwritten.

## For administrators

- Every change writes an audit entry and an outbox event in one transaction.
- Reference: the API under `/api/v1/assets`, `/api/v1/asset-saved-views`, `/api/v1/asset-categories`,
  `/api/v1/manufacturers`, `/api/v1/suppliers`; error codes in the
  [generated reference](../../reference/error-codes.md).
