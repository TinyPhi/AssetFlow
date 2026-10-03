<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Member provisioning policies

Every organization picks one sign-in policy, stored in `organizations.settings.provisioning`
(set by `--provisioning` on [`assetflow org create`](create-organization.md), default
`invite_only`). It decides what happens the first time a principal with no member row yet signs
in; a principal that already has a member (matched by IdP subject) always signs in regardless of
policy.

- **`invite_only`** (default): only an administrator-invited member can sign in. The invite links
  automatically on the first sign-in whose email matches an invited member's email exactly
  (case-insensitive) and whose email is verified by the identity provider. A principal with no
  matching invite is refused.
- **`require_role`**: any principal whose token carries at least one AssetFlow role is provisioned
  automatically, with that role granted at organization scope. A principal with no role is
  refused.
- **`open`**: any authenticated principal is provisioned automatically, with a minimal `member`
  role if the token carries none. Development and test only unless
  `platform.allow_open_provisioning: true` is set (checked at startup, not per request).

Suspension (organization or member) is checked on every request, never cached: a suspended
principal is still recognized, so it is told its request is out of scope (404), not that it is
unauthenticated.
