<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0008: Config-Driven Workflow and Automation Engines with Structured Conditions

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, Product Engineering
- **Revisions / Supersedes:** Reaffirmed in §B7.3, §B8, §B9.

---

## 1. Context and Problem Statement

Asset lifecycles and maintenance procedures differ across industries (e.g. IT asset disposition vs. heavy rail maintenance). Hardcoding lifecycle states or transitions into business code forces code forks across customer domains. Conversely, allowing arbitrary Python or JavaScript expressions creates severe code-injection vulnerabilities.

---

## 2. Decision Outcome

Implement generic, declarative Workflow (state machine) and Automation (event-condition-action) engines in core. All conditions must use structured declarative syntax (field, operator, value) serialized in YAML/JSON. Free-text code evaluation (`eval`, `exec`) is strictly prohibited.

---

## 3. Consequences

### Positive & Negative Impact
- Good: New industry domains are created purely via YAML templates (`config/domains/*.yaml`), zero code modifications.
- Good: Eliminates remote code execution (RCE) attack vectors in user-defined business rules.
- Cost: Condition expression syntax is limited to supported structured operators (equals, in, greater_than, etc.).

---

## 4. Alternatives Considered

- Embedded scripting engines (Python `eval()`, Lua, or embedded JS): Rejected due to unacceptable sandboxing escape risks and security attack surfaces.
- Hardcoding state machines in Python code: Rejected because it breaks generic open-source design principles.

---

## 5. References

- Master Plan §B3 (D8), §B7.3, §B8, §B9.
