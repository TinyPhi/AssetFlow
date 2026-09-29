<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0002: Clean Repository Without Legacy History Import

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, TinyPhi Legal & Governance
- **Revisions / Supersedes:** Reaffirmed in §B2.1, §D1 Gate G0.6.

---

## 1. Context and Problem Statement

AssetManager and legacy TMMS git histories contain internal organization identifiers, customer references, internal infrastructure IP addresses, unrotated credential artifacts, and proprietary project notes. Preparing the codebase for open-source distribution requires pristine intellectual property hygiene.

---

## 2. Decision Outcome

Create a completely new, clean git repository (`AssetFlow`) with zero history import from previous projects. Source code and components are ported module-by-module through scrutinized pull requests after scrub, domain-term normalization, and license compliance verification.

---

## 3. Consequences

### Positive & Negative Impact
- Good: Absolute confidence that no internal operational secrets, proprietary documents, or customer PII enter public history.
- Good: Establishes a clean Conventional Commits record from commit zero.
- Cost: Historical commit attribution from legacy internal repositories is severed; addressed by tracking original provenance in `docs/provenance.md`.

---

## 4. Alternatives Considered

- `git filter-repo` / BFG history rewriting: Rejected because regex history scrubbers cannot guarantee 100% elimination of semantic secrets or confidential context across hundreds of past commits.
- Publishing the existing repository directly: Rejected due to critical security and intellectual property risks.

---

## 5. References

- Master Plan §B3 (D2), §B2.1, §B14.1, §C2.1.
