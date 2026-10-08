<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# Architecture Decision Records (ADRs)

This directory records architectural decisions made for AssetFlow per master plan §B3 (D1–D18) and §C6.5.

| ADR | Decision Title | Status | Date |
| --- | --- | --- | --- |
| [0001](ADR-0001-modular-monolith.md) | Python 3.12 / FastAPI Modular Monolith with React 19 SPA | `Accepted` | 2026-09-23 |
| [0002](ADR-0002-clean-repository.md) | Clean Repository Without Legacy History Import | `Accepted` | 2026-09-23 |
| [0003](ADR-0003-pluggable-providers.md) | Pluggable Provider Interfaces for Core Infrastructure | `Accepted` | 2026-09-23 |
| [0004](ADR-0004-postgresql-rls-multi-tenancy.md) | Organization Multi-Tenancy Enforced via PostgreSQL Row-Level Security | `Accepted` | 2026-09-23 |
| [0005](ADR-0005-uuidv7-primary-keys.md) | UUIDv7 Primary Keys and Configurable Human-Readable Sequences | `Accepted` | 2026-09-23 |
| [0006](ADR-0006-alembic-raw-sql-migrations.md) | Alembic Raw SQL Migrations and Security Invoker Views | `Accepted` | 2026-09-23 |
| [0007](ADR-0007-scoped-rbac.md) | Permission-Based Scoped Role-Based Access Control | `Accepted` | 2026-09-23 |
| [0008](ADR-0008-workflow-automation-engines.md) | Config-Driven Workflow and Automation Engines with Structured Conditions | `Accepted` | 2026-09-23 |
| [0009](ADR-0009-transactional-outbox-worker.md) | Transactional Outbox Pattern and Dedicated Background Worker | `Accepted` | 2026-09-23 |
| [0010](ADR-0010-agpl3-commercial-dual-license.md) | AGPL-3.0 License with Commercial Dual-Licensing and Contributor License Agreement | `Proposed` | 2026-09-23 |
| [0011](ADR-0011-bff-refresh-cookie-auth.md) | Backend-for-Frontend (BFF) HttpOnly Refresh-Cookie Authentication | `Accepted` | 2026-09-23 |
| [0012](ADR-0012-neutral-domain-vocabulary.md) | Neutral Domain Vocabulary and Configurable Display Labels | `Accepted` | 2026-09-23 |
| [0013](ADR-0013-hierarchical-org-units-and-teams.md) | Hierarchical Org Units via PostgreSQL Ltree and Cross-Cutting Teams | `Accepted` | 2026-09-23 |
| [0014](ADR-0014-web-only-api-first.md) | Web-Only 1.0 Release with API-First Design | `Accepted` | 2026-09-23 |
| [0015](ADR-0015-builtin-inbox-and-channel-connectors.md) | Built-in Inbox and First-Party In-Process Notification Channel Connectors | `Accepted` | 2026-09-23 |
| [0016](ADR-0016-html-weasyprint-pdf-rendering.md) | PDF Generation from HTML Templates via WeasyPrint | `Accepted` | 2026-09-23 |
| [0017](ADR-0017-pydantic-json-schema-driven-forms.md) | Pydantic JSON Schema-Driven Connector and Provider Configuration | `Accepted` | 2026-09-23 |
| [0018](ADR-0018-break-glass-access.md) | Time-Limited Audited Break-Glass Access for Identity Provider Outages | `Accepted` | 2026-09-23 |
| [0019](ADR-0019-database-roles-and-login-users.md) | Database Roles and Login Users Standard | `Accepted` | 2026-10-01 |
