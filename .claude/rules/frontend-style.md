---
paths:
  - "frontend/**"
---

# Frontend style

Source: plan §B4.3, §B10, §B11.1 (browser), §B12.4, §C1.3, §C1.7, §C4.9, §C4.10, §C8.7, §C12.

## Toolchain

- React 19 SPA, TypeScript `strict` (no unchecked index access, exact optional properties), ESLint typescript-eslint strict type-checked + react, react-hooks, jsx-a11y, security rules; Prettier print width 110; vitest + Testing Library + MSW.
- Run `make fmt`, `make lint`, `make typecheck`, `make test-frontend` before `af.py verify`.

## File header

```ts
// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only
```

JSON and translation files are covered by `REUSE.toml`.

## Structure (§C4.9)

`frontend/src/`: `app/` (shell, routing, guards), `features/{assets,maintenance,organization,notifications,audit,admin,settings}/`, `components/ui/`, `lib/{api,auth,config,permissions,i18n}`, `styles/tokens.css`.

Each feature folder: `api/` (service functions over `lib/api` + query-key factory), `hooks/` (TanStack Query hooks), `components/`, `pages/`, `routes.tsx` (routes with permission guards), `index.ts` (public exports).

## Rules

- Data flow: component -> hook -> `api/` service -> `lib/api`. Components never call `fetch` or axios.
- Server state only through TanStack Query. Query keys from a factory: `workOrderKeys.list({ state: "open" })`.
- No `any` (use `unknown` with type guards). No `console.*` outside the dev-only logger.
- Permission-aware UI: `usePermission("work_order.dispatch", workOrder)`. The UI hides actions for convenience only; **the API always decides**.
- Every list page has four states: loading (skeleton), error (with retry), empty (with a call to action), data.

## Auth and browser security (D11, §B11.2)

- The browser holds **no credentials**. The refresh token lives in the HttpOnly BFF cookie; the access token is kept **in memory only**. Never `localStorage`, `sessionStorage` or IndexedDB for tokens.
- Refresh via `/api/auth/refresh`, single-flight, with header `X-Requested-With: AssetFlow`. Failure signs the user out.
- Public OIDC client with PKCE; no client secret in the bundle. `/api/config/public` is the only config source.
- No `dangerouslySetInnerHTML` (lint rule). No inline scripts or styles (strict CSP). No third-party origins beyond the IdP and the configured telemetry endpoint.

## Text and i18n (§C1.7)

- All UI text through `t("<feature>.<screen>.<element>")`, e.g. `t("work_orders.board.empty_state")`. No raw strings in JSX (lint rule).
- Every key used exists in `frontend/src/lib/i18n/locales/en.json` (CI check).
- Use neutral domain terms in keys and code (`member`, `org_unit`, `work_order`); display labels come from the domain `vocabulary`.
- US English, sentence case for headings and buttons. Dates in UTC from the API, shown per organization/member timezone and locale.
- Error messages: branch on the RFC 9457 `code`, translate the title through i18n; show `errors[]` per field.

## Styling and layout (§B10)

- Tailwind utilities with semantic tokens only (`bg-surface`, `text-danger`). No raw palette classes, no hex values (theme-regression test).
- Responsive from 320 px to 2560 px+, portrait and landscape: no sideways scroll, tables become cards on narrow screens, navigation collapses, touch targets at least 44 px.
- WCAG 2.2 AA: semantic elements, labels on inputs, visible focus, logical tab order, no focus traps.

## Forms

- Connector and provider settings forms are generated from the JSON Schema served by the API, with a Zod validator built from it (D17). No hand-written connector forms.
- Hand-written forms use Zod schemas that mirror the Pydantic schema. The server validates again.
- Secret fields are write-only: show "set / not set", never the value.

## Naming (§C1.3)

- Module files kebab-case (`work-order-service.ts`); components PascalCase (`WorkOrderBoard.tsx`).
- Functions and variables camelCase; hooks `use<Noun|Verb>` (`useDispatchWorkOrder`).
- API JSON fields stay snake_case as received; do not rename at the boundary without a typed mapper.
- Tests: `<unit>.test.ts(x)` next to the code.
