---
description: Review a feature spec against the §C6.6 template with the spec-reviewer agent
argument-hint: "[docs/specs/<name>.md]"
---

1. Resolve the spec: `$ARGUMENTS`, or the most recently modified file in `docs/specs/` if none is given.
   If the file does not exist, say so and suggest `/spec <name>`.
2. Invoke the `spec-reviewer` agent with the spec path. Tell it to check §C6.6, §C4.8, §C5.4 and §C1, and to verify
   that referenced files, tables and routes exist.
3. Relay its table, blocking items, caveats and questions to the lead engineer without softening them.
4. By verdict:
   - `READY` — suggest `/spec-tasks <spec path>`.
   - `READY WITH CAVEATS` — list the caveats; ask whether to fix them now (edit the spec) or record them in the
     spec's Change log and continue to `/spec-tasks`.
   - `NOT READY` — offer to resume `/spec` on the missing sections. Do not create tasks or a plan.
5. Do not change the spec's `Status` to `approved`; only the lead engineer approves a spec.
