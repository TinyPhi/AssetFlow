---
name: doubt-driven
description: Fresh-context adversarial review for high-risk AssetFlow changes - RLS policies, auth/session, grants and scope resolver, SECURITY DEFINER functions, public scan/report, channel runtime egress. Use PROACTIVELY before REVIEW when the diff touches tenancy, auth or scope; also for "double-check", "are we sure", "prove this is safe", "doubt this".
---

# Doubt-driven review

The author's context is biased toward believing the change works. This skill assumes it is wrong until a fresh
reviewer fails to break it. Maximum 3 cycles.

## When it is required

The diff touches any of: `backend/migrations/` (policies, grants, functions, views), `backend/app/core/db*`,
`backend/app/core/permissions*`, `backend/app/core/auth_middleware.py`, `backend/app/providers/auth/`,
`backend/app/modules/organization/` (grants, provisioning), `backend/app/modules/assets/qr/public*`,
`backend/app/channels/base.py`, or any repository list method / `ScopeFilter`.

## Cycle

1. **Claim.** Write the change's safety claims as falsifiable statements, e.g.
   - "A member of org_b cannot read, list, update or infer any org_a work order through any route or view."
   - "A member scoped to North cannot see a South work order in list or detail; a record in two scope branches appears once."
   - "An unstamped connection sees zero rows of `<table>` and cannot insert."
   - "Only `assetflow_api` can execute `platform.resolve_organization`, and it returns only `(id, status)` for one IdP org."
2. **Fresh reviewer.** Spawn a new agent with no conversation history (`security-reviewer`, or a general agent in read-only mode).
   Give it ONLY: the claims, `git diff HEAD`, and the paths of the relevant tests. Not your reasoning, not the plan narrative.
   Ask: "Find an input, role, sequence or timing that falsifies a claim. Cite file:line. Propose a test that would show it."
3. **Adjudicate.** For each attack:
   - write the proposed test (`backend/tests/isolation/`, `scope/`, `authz_matrix/`, `contract/`) and run it;
   - test fails -> real finding: fix it (one writer pass), keep the test;
   - test passes -> attack refuted; keep the test if it covers a case not covered before.
   No attack is dismissed by argument alone.
4. **Repeat** with a new fresh reviewer and the updated diff until a cycle yields no confirmed finding, or 3 cycles are used.

## Attack checklist to hand the reviewer

- Missing `set_config('app.organization_id', $1, true)` path (raw pool connection, background task, worker without `worker_context`).
- Policy with `USING` but no `WITH CHECK`; `FORCE` missing; view without `security_invoker`; table owner = API role.
- `SECURITY DEFINER` without pinned `search_path`, unqualified names, `EXECUTE` still granted to `PUBLIC`, returns too much.
- `ScopeFilter` bypass: new list method without it, `OR` instead of `UNION ALL`, org-scope shortcut applied to a narrower grant,
  cursor or count computed before de-duplication.
- 403 vs 404 or timing difference revealing existence across scope or organization.
- Grant escalation: granting a role containing a permission the granter lacks; `*` matching `platform.*`.
- Grant cache: revoked grant still honored after `grants_changed`; lost `LISTEN` connection not clearing the cache.
- Invite linking without `email_verified=true` or with a case-variant email; re-linking an existing member by email.
- Public scan: token accepted unhashed, tag accepted without token, fields beyond `public_scan_fields`, missing rate limit.
- Egress: DNS rebinding to `127.0.0.1` between check and connect; redirects to private addresses; HTTP not HTTPS.

## Exit

- Clean cycle: record in the review JSON `findings_triaged` (accepted/deferred/rejected with the test names) and continue to REVIEW.
- Still a confirmed finding after cycle 3: write `docs/tracker/BLOCKERS.md` with the claim, the attack, the failing test,
  and stop. Do not weaken a test or a claim to get a clean cycle.
