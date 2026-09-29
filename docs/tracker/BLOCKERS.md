# Blockers Log

Table of blockers encountered during development. Stop and record here when a task cannot proceed.

| Date | Task ID | Blocker | Evidence | What was tried | Decision needed | Resolved |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-09-29 | P0-03 | Real secrets exist in the old code (4 private keys, live JWT/client secrets in `.env*`, per provenance-scan.md) | provenance-scan.md §5 | Never copied; not enough on its own | Owner rotates every found credential; new values live only in OpenBao | ☐ |
