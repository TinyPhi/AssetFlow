<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

---
name: Release Checklist
about: Process checklist for cutting an official AssetFlow release.
title: "Release: vX.Y.Z"
labels: ["release-blocker"]
---

## Release Information
- **Target Version:** `vX.Y.Z`
- **Release Manager:** @
- **Branch:** `release/vX.Y.Z`

---

## 1. Pre-Release Verification
- [ ] All target milestone issues and PRs are merged or deferred.
- [ ] CI pipeline (`ci-complete`) is 100% green on `main`.
- [ ] `make test-isolation` passes (RLS fail-closed, multi-org isolation, scope leak tests).
- [ ] `make test-contract` passes on all providers and channels.
- [ ] Database migration rollback test passes (`upgrade head -> downgrade -1 -> upgrade head`).
- [ ] `uvx reuse lint` passes with 0 license errors.
- [ ] Static vulnerability scans (Trivy, CodeQL, pip-audit, npm audit) contain zero **Critical** or unmitigated **High** findings.

## 2. Changelog & Documentation
- [ ] `CHANGELOG.md` updated: moved items from `[Unreleased]` into `[vX.Y.Z] - YYYY-MM-DD`.
- [ ] All new configuration settings in `config/` are documented in `docs/operations/`.
- [ ] Any breaking changes or deprecations are highlighted with migration paths.

## 3. Build & Tag
- [ ] Create signed git tag: `git tag -s vX.Y.Z -m "Release vX.Y.Z"`.
- [ ] Verify container builds for `api`, `worker`, and `web`.
- [ ] Verify cosign image signing and SLSA Level 2 provenance generation in CI.

## 4. Post-Release & Announcement
- [ ] Publish GitHub Release with release notes and contributor attributions.
- [ ] Verify deployment using `compose.minimal.yml` and `compose.full.yml` from released artifacts.
- [ ] Announce release in GitHub Discussions and community channels.
