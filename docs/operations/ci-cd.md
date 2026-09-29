<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# CI/CD and GitHub Repository Operations

This document defines the automated CI/CD pipeline architecture and repository branch/tag protection settings for AssetFlow per §B12.8 and §C2.5.

---

## 1. Branch Protection Rules (`main`)

The `main` branch holds production-ready, verified code. Direct commits and force pushes are strictly disabled.

When configuring GitHub branch protection rules for `main`:

| Setting | Value | Rationale |
| --- | --- | --- |
| **Require pull request before merging** | Enabled | Enforces peer review and definition-of-done checks (§C3). |
| **Required approvals** | 1 (general), 2 for security paths | Peer approval required; security paths governed by CODEOWNERS. |
| **Require review from Code Owners** | Enabled | Automatically requests `@TinyPhi/assetflow-security` for §C5.8 paths. |
| **Dismiss stale pull request approvals** | Enabled | New commits invalidate prior approvals to prevent unreviewed changes. |
| **Require status checks to pass** | Enabled (`strict`) | Branch must be up-to-date with `main` before merge. |
| **Required status checks** | `ci-complete`, `cla/check` | All unit, isolation, and compliance gates must be green. |
| **Require conversation resolution** | Enabled | All reviewer comments must be resolved before merge. |
| **Require linear history** | Enabled | Squash merge or rebase to keep git history clean and traceable. |
| **Allow force pushes** | Disabled | Prevents history tampering. |
| **Allow deletions** | Disabled | Prevents accidental branch deletion. |

---

## 2. Tag Protection Rules (`v*`)

Release tags represent immutable, signed release artifacts (§B12.8):

- **Tag pattern**: `v*` (e.g., `v1.0.0`, `v1.1.0-rc.1`).
- **Allowed actors**: Repository administrators and maintainers only (`@TinyPhi/assetflow-maintainers`).
- **Signature requirement**: All release tags must be cryptographically signed (`git tag -s vX.Y.Z -m "..."`).
- **Release workflow**: Pushing a signed tag `vX.Y.Z` triggers `.github/workflows/release.yml` to generate the Syft SBOM, sign container images with Cosign keyless SLSA Level 2 provenance, and draft release notes.

---

## 3. Security-Sensitive Paths & CODEOWNERS Enforcement

Under §C5.8 and §B12.7, any pull request modifying the following paths requires explicit sign-off from the security review team (`@TinyPhi/assetflow-security`) before GitHub allows a merge:

- `backend/app/core/permissions*`, `backend/app/core/db*`, `backend/app/core/auth_middleware.py`
- `backend/app/providers/auth/`, `backend/app/providers/secrets/`
- `backend/app/channels/base.py`
- `backend/app/modules/organization/`
- `backend/app/modules/assets/qr/public*`
- `backend/migrations/`
- `deploy/`, `.github/`, `scripts/check-*`

---

## 4. GitHub Actions Workflows Overview

| Workflow | Trigger | Description |
| --- | --- | --- |
| `ci.yml` | Pull Request, Push to `main` | Quality checks (linters, formatters, REUSE), backend unit/isolation tests, frontend tests, security scanners, aggregate `ci-complete` gate. |
| `contribution-checks.yml` | Pull Request | Enforces test presence for code changes, migration isolation tests, and validates absence of secrets/env files. |
| `security.yml` | Weekly cron | Comprehensive CodeQL, Semgrep, pip-audit, Trivy container scan, and OWASP ZAP baseline scan. |
| `scorecard.yml` | Weekly cron, Push to `main` | OpenSSF Scorecard supply-chain health and security posture. |
| `release.yml` | Tag `v*` | Multi-arch Docker images, Cosign keyless signatures, Syft SBOM, GitHub Release publishing. |
