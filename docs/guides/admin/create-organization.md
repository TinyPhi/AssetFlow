<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Create an organization

`assetflow org create` creates one organization, its root organization unit, and invites its first
administrator. It runs as an operator command outside any HTTP request.

## Before you start

1. Create the organization in the identity provider first: add `config/organizations/<slug>.yaml`
   (slug must equal the file name) and run `make zitadel-apply`. It prints the new Zitadel
   organization id, or stores it for a production run (see the file's own comments).
2. Have the first administrator's email ready. They are invited, not signed in automatically; they
   complete sign-in through the identity provider afterwards.

## Run it

```sh
cd backend
uv run python -m app.cli.org_create \
  --slug example-alpha \
  --admin-email admin@example-alpha.test \
  --idp-org <the Zitadel organization id from step 1>
```

`--name`, `--provisioning` and `--domain-key` are optional: `--name` falls back to the
organization file's `name`, `--provisioning` falls back to the file's `provisioning` and then to
`invite_only` (the other choices are `require_role` and `open`; see
[member provisioning](member-provisioning.md)), `--domain-key` defaults to `generic` (see
`config/domains/`).

The command is idempotent on `--slug`: running it again for an organization that already exists
prints "no changes" and does nothing further, even with different arguments.

## What it creates

In one transaction: the organization row, its root organization unit, the invited administrator
(`members.status = 'invited'`), an `admin` role grant at organization scope, an audit event, and an
outbox row (`organization.created`). The admin's email is stored only for the invite; it is never
logged, and the audit event redacts it like any other personal field (§1590).
