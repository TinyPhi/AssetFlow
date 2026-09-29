# AssetFlow

**AssetFlow** is an open-source, multi-tenant platform unifying **Asset Management** (lifecycle, custody, QR tracking, auditing) and **Maintenance Management** (the TMMS vision: work orders, preventive schedules, SLA tracking, automated dispatch).

- **Generic & Neutral**: Zero industry-specific or company-specific logic in core code. Every organization defines its asset schemas and workflows through declarative domain templates (`config/domains/*.yaml`).
- **Organization-Ready Multi-Tenancy**: Complete isolation enforced at the PostgreSQL layer via Row-Level Security (`FORCE ROW LEVEL SECURITY`) with scoped access across organization units, teams, and locations.
- **Modern Modular Monolith**: Python 3.12 / FastAPI backend + React 19 SPA frontend, backed by PostgreSQL 16 and asynchronous workers for transactional outbox dispatching and SLA evaluation.
- **Enterprise Provider Architecture**: Pluggable interfaces for Authentication (Zitadel OIDC preset), Secrets (OpenBao preset), Telemetry (OpenTelemetry OTLP), and Events.

---

## Architecture Overview

```
backend/app/        FastAPI application: core/ · providers/ · channels/ · engines/ · modules/ · api/v1/
backend/workers/    Async workers: outbox_dispatcher · schedule_evaluator · sla_sweeper
backend/migrations/ Versioned raw SQL & Alembic migrations with mandatory RLS policies
backend/tests/      unit/ · integration/ · isolation/ · scope/ · contract/ · authz_matrix/ · e2e_api/
frontend/src/       React 19 SPA: app/ · features/ · components/ui/ · lib/ · styles/tokens.css
config/             assetflow.yaml · domains/*.yaml · templates/
deploy/             compose.minimal.yml · compose.full.yml · bootstrap/ · nginx/ · grafana/
docs/               decisions/ (ADRs) · specs/ · guides/ · operations/ · security/ · reference/ · tracker/
scripts/            developer tooling · check-domain-terms.sh · verification runners
```

For detailed architectural decisions, see the [Architecture Decision Records (ADRs)](docs/decisions/README.md).

---

## Roadmap & Status

AssetFlow is currently in **Phase 1: Standards, Governance & Core Skeleton** (Gate G0 → Milestone M1.1).
Active milestones, progress logs, and verification criteria are tracked transparently in [`docs/tracker/roadmap-tracker.md`](docs/tracker/roadmap-tracker.md) and [`docs/tracker/PROGRESS.md`](docs/tracker/PROGRESS.md).

---

## Contributing

We welcome community contributions! Please review:
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — Contribution guidelines, Conventional Commits, and Definition of Done.
- [`CLA.md`](CLA.md) — Contributor License Agreement.
- [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) — Community standards.
- [`SECURITY.md`](SECURITY.md) — Vulnerability reporting policy.

---

## License

AssetFlow is licensed under the **GNU Affero General Public License v3.0** ([AGPL-3.0-only](LICENSE)).

Commercial licenses without copyleft requirements are available from **TinyPhi** for proprietary hosting, closed-source distribution, and enterprise integrations.
- Commercial inquiries: [licensing@tinyphi.com](mailto:licensing@tinyphi.com)
- Support & Services: [`SUPPORT.md`](SUPPORT.md)
