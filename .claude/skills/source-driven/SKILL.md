---
name: source-driven
description: Check official documentation before using or changing framework and platform APIs in AssetFlow (FastAPI, Pydantic v2, asyncpg, PostgreSQL 16, Alembic, uv, ruff, mypy, pytest, Zitadel, OpenBao, OpenTelemetry, React 19, Vite, TanStack Query), pinned to the versions in the lock files, and cite URLs. Use for "how does X work", "is this API correct", "upgrade", "deprecated", unfamiliar flags, or any security-relevant library call.
---

# Source-driven development

Memory of an API is a hypothesis. For anything non-trivial, and always for security-relevant behavior (RLS, `set_config`,
`SECURITY DEFINER`, token verification, OpenBao auth, CORS/CSP, cookies), confirm it in the official source for the
version the repository actually uses.

## 1. Find the version in use

- Python: `backend/uv.lock` (grep `name = "<pkg>"` then `version`), `backend/pyproject.toml` for ranges.
- Frontend: `frontend/package-lock.json` / `frontend/package.json`.
- Services: image tags in `deploy/compose.minimal.yml` and `deploy/compose.full.yml` (PostgreSQL 16, Zitadel, OpenBao, otel-lgtm).
- If unpinned or unclear, say so; do not assume latest.

## 2. Read the official source (versioned pages where they exist)

| Topic | Official source |
| --- | --- |
| FastAPI | https://fastapi.tiangolo.com/ (release notes: https://fastapi.tiangolo.com/release-notes/) |
| Pydantic v2 | https://docs.pydantic.dev/latest/ (pin: `/2.<minor>/`) |
| asyncpg | https://magicstack.github.io/asyncpg/current/ |
| PostgreSQL 16 | https://www.postgresql.org/docs/16/ (RLS: `ddl-rowsecurity.html`, `sql-createpolicy.html`; `functions-admin.html` for `set_config`; `sql-createfunction.html` "Writing SECURITY DEFINER Functions Safely"; `sql-createview.html` for `security_invoker`; `sql-createindex.html` for `CONCURRENTLY` and partitioned indexes) |
| Alembic | https://alembic.sqlalchemy.org/en/latest/ (`autocommit_block`: `api/runtime.html`) |
| uv | https://docs.astral.sh/uv/ |
| ruff | https://docs.astral.sh/ruff/ |
| mypy | https://mypy.readthedocs.io/en/stable/ |
| pytest / pytest-asyncio | https://docs.pytest.org/en/stable/ , https://pytest-asyncio.readthedocs.io/ |
| respx / httpx | https://lundberg.github.io/respx/ , https://www.python-httpx.org/ |
| PyJWT | https://pyjwt.readthedocs.io/en/stable/ |
| Zitadel | https://zitadel.com/docs (OIDC claims: `/docs/apis/openidoauth/claims`; roles `urn:zitadel:iam:org:project:roles`) |
| OpenBao | https://openbao.org/docs/ (AppRole: `/docs/auth/approle/`; KV v2: `/docs/secrets/kv/kv-v2/`; transit: `/docs/secrets/transit/`) |
| OpenTelemetry Python | https://opentelemetry.io/docs/languages/python/ |
| React 19 | https://react.dev/ (upgrade notes: https://react.dev/blog/2024/04/25/react-19-upgrade-guide) |
| Vite | https://vite.dev/guide/ |
| TanStack Query | https://tanstack.com/query/latest/docs/framework/react/overview |
| TypeScript | https://www.typescriptlang.org/docs/ |
| RFC 9457 | https://www.rfc-editor.org/rfc/rfc9457 |
| OWASP ASVS 5.0 | https://github.com/OWASP/ASVS |

Use WebFetch on the exact page. Prefer the project's own docs over blogs, Stack Overflow or AI summaries. Changelogs and
migration guides beat tutorials when behavior changed between versions.

## 3. Apply and cite

- Implement against what the source says for the pinned version. If the doc and the plan disagree, the plan's rule wins
  for AssetFlow behavior; flag the conflict to the lead engineer instead of choosing silently.
- Cite in the PR body (`## References`) and, only for a non-obvious why, in a code comment:
  `# PostgreSQL 16: SECURITY DEFINER must pin search_path - https://www.postgresql.org/docs/16/sql-createfunction.html`
- Add a test that pins the behavior you relied on (e.g. unstamped connection returns 0 rows), so an upgrade that changes it fails CI.

## 4. When the source is unavailable

Say "unverified" explicitly, keep the change minimal, and add the open question to the PR. Never invent flags,
parameters or defaults. For upgrades, read the release notes between the current and target versions and list
breaking changes before editing lock files (`uv lock --upgrade-package <pkg>`, `npm install <pkg>@<version>`).
