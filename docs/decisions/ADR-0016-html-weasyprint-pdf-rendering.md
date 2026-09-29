<!--
SPDX-FileCopyrightText: 2026 TinyPhi
SPDX-License-Identifier: AGPL-3.0-only
-->

# ADR-0016: PDF Generation from HTML Templates via WeasyPrint

- **Status:** Accepted
- **Date:** 2026-09-23
- **Deciders:** Lead Architect, Backend Team
- **Revisions / Supersedes:** Reaffirmed in §B1.3, §B4.1.

---

## 1. Context and Problem Statement

AssetManager used ReportLab for PDF generation. ReportLab drawing code is notoriously tedious to customize, difficult for open-source contributors to theme, and exhibits poor typography shaping for Indic and non-Latin scripts (e.g. Devanagari). Running headless Chromium browsers (Puppeteer) in container workers consumes excessive RAM (> 500MB per instance).

---

## 2. Decision Outcome

Render all PDF documents (custody forms, work order printouts, asset audit certificates) from Jinja2 HTML/CSS templates using WeasyPrint, bundled with open Google Noto fonts. Hardening rules enforce that local filesystem access and remote network asset fetching are strictly disabled during PDF rendering.

---

## 3. Consequences

### Positive & Negative Impact
- Good: Declarative HTML/CSS templating allows easy customization by administrators and contributors.
- Good: Flawless unicode and Indic script shaping support out-of-the-box with lightweight container memory footprint.
- Cost: Requires system Pango/Cairo C-libraries in container runtime images.

---

## 4. Alternatives Considered

- ReportLab Python drawing code: Rejected due to maintenance friction and lack of modern Indic font shaping.
- Headless Chrome / Puppeteer: Rejected because browser processes are too memory-heavy for single-node deployments.

---

## 5. References

- Master Plan §B3 (D16), §B1.3, §C5.10.
