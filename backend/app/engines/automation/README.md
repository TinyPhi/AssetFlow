# `backend/app/engines/automation`

Notification automation (§B7.3, §B6.3, M1.5-T2): given a domain event, find the matching
`automations` rules in the organization's domain template, resolve the recipients (holder, actor,
team, role at a scope) and channels, and produce one notification intent per (event, recipient,
channel). The workflow and SLA engines for maintenance (§B9.1-§B9.2) are a separate, later plan
(master Phase 3); nothing here evaluates SLAs or schedules.
