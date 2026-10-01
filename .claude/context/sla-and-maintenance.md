# Context: maintenance, schedules and SLA

Orientation for `backend/app/modules/maintenance/`, `engines/workflow/`, `engines/automation/`, `workers/schedule_evaluator.py`, `workers/sla_sweeper.py`. Plan sections: D8, §B5.4, §B7.3, §B9.1–§B9.3, §C8.3, §C8.6; delivery in §D4 (Phase 3, after Gates G2 and G3).

Maintenance work starts only after the maintenance spec is approved (Gate G3). Until then, do not build maintenance features; engines and data model only when a Phase 1/2 task asks for them.

## Config on shared engines (D8)

- Behaviour is data in `config/domains/*.yaml`, not code: work order types, priorities with response/resolution targets, `priority_matrix` (impact x urgency, criticality uplift), SLA pause states and warning threshold, `work_order_workflow`, escalation, routing rules, automations.
- **Workflow engine**: config-defined state machines; each transition has a permission, preconditions (e.g. mandatory tasks done) and optional required reason. Every transition -> `work_order_transitions` + audit.
- **Automation engine**: on event -> if structured condition -> do action. Conditions are `field` / operator / value with operators `equals`, `not_equals`, `in`, `not_in`, `lt`, `lte`, `gt`, `gte`, `exists`, `all`, `any`. Fields limited to a registered list per event. **Never evaluate free-text expressions.**
- Engines know nothing about modules; modules register entities, actions and conditions.

## Core entities (§B9.2)

`work_requests` (open/triaged/rejected) -> triage -> `work_orders` (number from per-organization sequence, state, priority, impact, urgency, severity, assignee member/team, `owner_org_unit_path`, source). Also `maintenance_plans`, `maintenance_schedules`, `maintenance_schedule_assets`, `work_order_tasks`, `work_order_transitions`, `downtime_records`, `sla_events`.

## Schedules, per asset

- A schedule links a plan to a target: one asset, or every asset in a category, org unit or location.
- Triggers: **calendar** (RFC 5545 `rrule`, `fixed` from planned date or `floating` from last completion) or **meter** (every N units).
- Lead time, grace window, suspension while the asset is retired or already under maintenance.
- **Per-asset state** lives in `maintenance_schedule_assets(schedule_id, asset_id, next_due_at, last_completed_at)`, so group schedules track each asset separately.
- Generation is idempotent: `UNIQUE (organization_id, schedule_id, asset_id, due_at)` on `work_orders`; group schedules create one work order per asset.
- The schedule evaluator runs every minute, claims due schedules in batches, one organization context at a time, and emits `work_order.created`.

## SLA: four precomputed timers

- Response and resolution targets per priority, on the working calendar of the assigned team or the organization (holidays included).
- When the clock starts, pauses or resumes, the **service** computes four timestamps: `sla_response_warn_at`, `sla_response_breach_at`, `sla_resolution_warn_at`, `sla_resolution_breach_at`. No calendar maths during sweeps.
- Pause in configured states (e.g. on hold); `sla_paused_seconds` accumulates.
- Response clock stops at the first response (leaving the initial state); resolution clock stops at completion. `sla_result` stored per work order.
- Changing a working calendar does not recalculate open work orders; the admin screen warns how many keep their earlier due times.
- The SLA sweeper (every minute) selects open work orders where a timer is `<= now` and no `sla_events` row exists for that (target, kind); emits `work_order.sla_warning` / `work_order.sla_breached` **exactly once** per target and level. `sla_events` is unique on (`work_order_id`, `target`, `kind`) for warning and breach. Partial indexes on the four timers (open work orders only).
- Escalation (1.0: two levels): warning -> team lead; breach -> org unit manager of the asset's owner (per template). Each escalation is an event and an audit record.

## Other rules

- Priority from the matrix, raised by criticality if configured. Manual override needs `work_order.override_priority` and a reason.
- Downtime starts when a work order enters `in_progress` on an asset whose category requires it; the asset becomes `under_maintenance` and is restored afterwards.
- Failed checklist item with high severity can create a follow-up corrective work order (automation).
- Due-soon / overdue sweeper every 15 min, once per work order and threshold.

## Tests (§C8.3, §C8.6)

- Table-driven: whole priority matrix, every transition allowed and refused, each condition operator.
- Hypothesis: SLA clock never goes backward; pause/resume never shortens a deadline; each warning is at or before its breach.
- Worker: run twice -> one work order per due period; two workers at once -> no duplicates.
- E2E: request -> triage -> work order -> dispatch -> start (downtime) -> checklist -> complete; schedules with the test clock; SLA warning and breach fire once, honouring calendar and pause.
