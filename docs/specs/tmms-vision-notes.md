<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# TMMS Product Vision Capture & Requirements Brief Notes

**Document:** `docs/specs/tmms-vision-notes.md`  
**Task:** P4-02 (Gate G0.7 / Milestone M3.0 / Master Plan §B9, §B14.2)  
**Target Milestone:** M3.0 Maintenance Engine Brief & Technical Specification  
**Source Prototype Audited:** `individual-projects/TMMS-WEB/` (read-only architectural audit)  
**Rule:** No TMMS code or SQL is copied; concepts are refined into AssetFlow's cleanroom architecture (§B14.2).  
**Received by the requirements owner:** pending (Q15)

---

## 1. Executive Summary & Vision Statement

The **TMMS** prototype introduced a product vision for high-reliability, distributed maintenance management. While the original prototype served only as an early technical proof-of-concept with synchronous Kafka messaging and basic ping task submission, the operational product vision addressed critical industrial maintenance capabilities:
- Real-time fault reporting and structured triage.
- Priority- and severity-driven maintenance workflows.
- Planned preventive maintenance and meter-based scheduling.
- SLA monitoring with proactive escalation before breach.
- Mobile-first technician workflows for field execution.
- Real-time notifications across in-app, email, and webhook channels.

AssetFlow generalizes this vision across multiple industrial domains (IT equipment, facilities, fleet, and communications infrastructure) via domain templates (`config/domains/*.yaml`), PostgreSQL transactional outbox, and multi-tenant RLS (§B9).

---

## 2. Vision Mapping: Prototype vs. AssetFlow 1.0 Cleanroom Design

| Vision Capability | Prototype Reality (`TMMS-WEB`) | AssetFlow 1.0 Cleanroom Design (§B9, §B14.2) |
| :--- | :--- | :--- |
| **Work Requests** | Generic task submission form (`frontend/src/pages/dashboard.tsx`) submitting raw ping tasks. | Formal `work_requests` entity: problem description, asset/location tag, severity level, optional public QR reporting with rate-limiting, and dedicated triage workflow (`work_request.triage`). |
| **Priority & Severity** | *Not in the prototype.* | Structured `Impact × Urgency` matrix, plus asset criticality uplift (`config/domains/*.yaml`). Explicit distinction between fault *severity* and work order *priority*. |
| **Work Order Lifecycle** | *Not in the prototype.* | Config-driven finite state machine (`maintenance.work_order_workflow`): Scheduled &rarr; Dispatched &rarr; In Progress &rarr; On Hold &rarr; Completed / Cancelled, with permission gates and required transition reasons. |
| **SLA & Escalation** | *Not in the prototype.* | Working-calendar aware response and resolution timers. Automatic pause during On Hold. Proactive warning threshold and breach event dispatch to team leads and org unit managers. |
| **Preventive Maintenance** | *Not in the prototype.* | Reusable `maintenance_plans` linked to `maintenance_schedules` via calendar rules (fixed or floating) or meter thresholds (hours, km, cycles). |
| **Smart Routing & Dispatch** | *Not in the prototype.* | Domain routing rules automatically assign work orders based on asset category or location. Dispatch board with team and member workload visibility. |
| **Execution & Checklists** | *Not in the prototype.* | Structured `work_order_tasks`: pass/fail/skip checks, numeric readings with tolerance limits, and automated follow-up work order creation upon critical check failure. |
| **Downtime Tracking** | *Not in the prototype.* | Automatic downtime logging on assets when work orders enter `in_progress`. Computes MTTR, availability, and restores status upon completion. |
| **Technician Experience** | Browser web view with task list (`dashboard.tsx`) and health badge. | Mobile-responsive touch-first interface (minimum 44px tap targets, 320px–2560px viewports) with QR scanning verification. |
| **Real-Time Notifications** | *Not in the prototype.* | Full event-driven notification dispatch for maintenance event set (`work_request.created`, `work_request.triaged`, `work_request.rejected`, `work_order.created`, `work_order.dispatched`, `work_order.in_progress`, `work_order.on_hold`, `work_order.sla_warning`, `work_order.sla_breached`, `work_order.completed`, `work_order.cancelled`) to in-app bell, email, and webhooks (§B9.1). |
| **Messaging & Events** | Synchronous Kafka producer (`backend/app/utils/kafka_producer.py`). | PostgreSQL Transactional Outbox (change + audit + event in one atomic transaction) claimed by `assetflow-worker` with `SKIP LOCKED`. |

---

## 3. Cleanroom Architecture Framework for Milestone M3.0

### 3.1 Work Requests & Triage Workflow (UF6)
1. **Intake:** Authenticated members (or anonymous public QR scans if enabled) submit a work request specifying `asset_id`, `location_id`, `description`, and `severity`.
2. **Triage:** Planners or team leads review incoming requests:
   - **Accept:** Converts request to a work order. Impact and urgency are assigned, determining priority via the domain matrix.
   - **Reject:** Closes request with a mandatory reason; requester receives automated rejection notification.

### 3.2 Dynamic Priority Matrix & Criticality Uplift
- **Matrix Calculation:** `Priority = Matrix[Impact, Urgency]`.
- **Criticality Uplift:** If an asset's category or profile defines high criticality (e.g. Tier-1 core infrastructure), the priority is elevated by one level (e.g. P2 &rarr; P1).
- **Manual Override:** Requires specific `work_order.override_priority` permission and an audit justification.

### 3.3 SLA Engine & Working Calendar
- **Response Target:** Clock begins at work order creation/dispatch and stops at the **first response** (§B9.1) (e.g. triage acknowledgement or assignment).
- **Resolution Target:** Clock stops when work order transitions to `completed`.
- **Precomputed Timestamps:** `sla_response_warn_at`, `sla_response_breach_at`, `sla_resolution_warn_at`, `sla_resolution_breach_at` are calculated at transition time using team working calendars, ensuring database sweeps require zero runtime calendar math.

### 3.4 Preventive Schedules & Meter Triggers (UF7)
- **Calendar Mode:** Evaluated by background worker every minute.
  - *Fixed:* Due dates calculated from planned recurrence.
  - *Floating:* Due dates calculated from last completion timestamp.
- **Meter Mode:** Evaluated when technicians record readings during routine rounds. Due when cumulative value exceeds trigger threshold.
- **Idempotency:** Unique index on `(organization_id, schedule_id, asset_id, due_at)` guarantees zero duplicate work order generation.

### 3.5 Field Execution Checklists & Downstream Automations
- **Checklist Types:** Pass/Fail boolean, numeric meter reading with upper/lower bounds, or text note.
- **Automated Escalation Rule:** If a task with `severity_on_fail=critical` fails, the automation engine creates an immediate corrective work order linked to the asset.

---

## 4. Open Questions for the Requirements Brief (Gate G0.7 / Q1, Q15)

The following proposals are submitted as open questions for the Requirements Owner to decide in the official One-Page Maintenance Brief:
1. **Priority Scale:** Does the domain require 4 or 5 priority levels (e.g. Critical, High, Medium, Low, Routine)?
2. **SLA Targets:** What are the default response and resolution durations per priority tier (e.g. P1: 15 min response, 2 hr resolution)?
3. **SLA Warning Threshold:** Should the proactive warning event fire at 20% remaining time or at a fixed interval?
4. **Checklist Tolerances:** Are checklist readings strict blockers for completion, or can a technician proceed with a warning?
5. **Auto-routing Precedence:** When both asset category and location specify default teams, which team takes routing precedence?

---

*Verified: Cleanroom architectural capture complete. No prototype code or database schemas copied into AssetFlow.*
