# admin-frontend

> Frontend for the Ithina Superadmin Governance Console. Sibling to `admin-backend`. Solo build, Claude Code as agent.

---

## What this is

The operator surface for the Ithina platform. Eight pages grouped as Overview (Dashboard), Governance (Tenants, Org Tree, Users), Access Control (Roles, Module Access, Guardrails), Compliance (Audit Log). Plus auth surfaces, profile, notifications, and impersonation banner.

The product is referred to as "Ithina Superadmin Console" externally and codenamed "SmartSave" internally. Both refer to this artifact.

---

## v0 scope

**One-day target: functional layout shells across all 8 pages plus implied surfaces.** Roughly 70% visual fidelity to the Lovable prototype, 90% structural fidelity, 40% interactive fidelity. Pixel polish, animation polish, validation rules, optimistic updates, accessibility polish, and real Auth0 screens are deferred to later passes.

**v0 backend is read-only.** Frontend renders all pages but mutations are non-functional:
- Page-level primary CTAs (e.g. "+ Provision tenant") render, click toasts "Coming in v1"
- Row-level kebab actions hidden entirely in v0
- All data hooks mock-first; backend endpoints swap in incrementally as backend ships them across its 10-day timeline

**Wiring is incremental, not all-at-once.** Backend lands one resource at a time over its 10 days. Frontend's MSW config lets each endpoint flip from mock to real independently, no component changes required.

---

## Stack

| Layer | Choice |
|---|---|
| Framework | Next.js 14+ (App Router) |
| Language | TypeScript (strict) |
| Styling | Tailwind CSS |
| Components | shadcn/ui |
| Server state | TanStack Query |
| Mocking | MSW (Mock Service Worker) |
| Forms | React Hook Form + Zod (when validation lands) |
| Auth | @auth0/nextjs-auth0 (production), persona switcher (dev) |
| Package manager | pnpm |

---

## Source of truth

The backend repo (`admin-backend`) is authoritative for all architectural and contract decisions. This frontend treats those docs as external sources of truth. Where the Lovable prototype's frontend spec contradicts backend architecture, backend wins.

Key external references (read in `admin-backend` repo):

- `docs/architecture.md` — system architecture, request lifecycle, multi-tenancy model
- `docs/api-contract.md` — frontend API contract (recommendations are locked for v0)
- `docs/tenants-api-contract-v0.md` — frontend dev's draft contract per page (use as a starting point, defer to backend reality where they conflict)
- `CLAUDE.md` — backend decisions D-01 through D-27, JWT claim shape, error model

For the design reference (functional spec only, not a contract):

- `Ithina_Admin_Frontend.md` — Lovable prototype spec, 8 pages, 25 open questions

---

## API contract (locked for v0)

| Decision | Value |
|---|---|
| URL prefix | `/api/v1/` |
| Auth | `Authorization: Bearer <jwt>` on every request except `/api/v1/health`, `/api/v1/docs`, `/api/v1/openapi.json`, `/metrics` |
| Response field naming | snake_case |
| List envelope | `{items: [...], pagination: {total, offset, limit}}` |
| Pagination | offset/limit |
| Timestamps | ISO 8601 UTC with `Z` suffix |
| Error shape | `{code, message, details, request_id}` |
| Money | fixed-point string (e.g. `"142000.00"`) |
| Enums | raw string values (`"ENTERPRISE"`); display labels from `/api/v1/lookups` |
| Nulls | always present (never omitted) |

JWT custom claims (Auth0-compatible namespace; matches backend D-24 identity-only shape):

```
https://ithina.com/tenant_id    UUID or null
https://ithina.com/user_type    "PLATFORM" | "TENANT"
https://ithina.com/user_id      UUID
https://ithina.com/email        string
```

Roles and permissions resolve in-app per request, not from the JWT. The frontend keeps a `roles: string[]` field on the local `Persona` type for stub-mode display only (role chips on persona cards, top-bar role label); these are not signed into the token.

---

## Auth during build phase

Auth0 ops setup is not yet complete. Frontend ships in a hybrid mode:

1. **Production code path** — `@auth0/nextjs-auth0` SDK wired structurally. Login, logout, token refresh, callback all routed through Auth0's hosted screens. Hidden behind feature flag during build.

2. **Dev escape hatch** — `/dev/login` persona switcher. Pre-minted RS256 JWT fixtures (matching the backend's stub claim shape). Pick a persona, get redirected to dashboard with token in memory.

Personas scaffolded for v0:

- Anjali Mehta — Super Admin (PLATFORM, no tenant_id)
- Marcus Tanner — Owner of Buc-ee's (TENANT)
- Kira Yilmaz — Support Admin (PLATFORM, used to verify the impersonation banner shape)

Env flag `NEXT_PUBLIC_AUTH_MODE=stub|auth0` toggles between modes. When Auth0 lands, flip to `auth0` and the persona switcher hides in prod.

---

## Mock data strategy

Three layers in the data plane. Components only ever see hooks; they never know whether data is mocked or real.

```
Component
   │
   ▼
useTenants(), useUser(id), etc.   <- TanStack Query hooks
   │
   ▼
Typed API client (fetch wrappers, one per resource)
   │
   ▼
Network layer
   │
   ▼ (intercepted in dev by MSW)
   │
MSW handlers <-- per-endpoint config: mock | real
   │
   ▼
Fixtures (from ithina_dev_seed_data.xlsx + Appendix E)
```

Per-endpoint mock toggle lives in `mocks/config.ts`. Flip an entry from `"mock"` to `"real"` when the backend ships that endpoint. No component changes.

Fixtures match the backend's eventual seed data so when wiring flips from mock to real, the UI renders the same thing visibly. Continuity is the point.

---

## Pages and v0 status

| Page | Path | v0 status | Backend dependency |
|---|---|---|---|
| Dashboard | `/superadmin/dashboard` | Mocked | Aggregates over multiple tables |
| Tenants | `/superadmin/tenants` | Mocked, wires first | `GET /api/v1/tenants` (backend Step 3.3) |
| Org Tree | `/superadmin/org` | Mocked | `org_nodes` (backend Step 5.3) |
| Users | `/superadmin/users` | Mocked | `platform_users` + `tenant_users` (backend Steps 5.1, 5.2) |
| Roles & Permissions | `/superadmin/roles` | Mocked | RBAC tables (backend Step 6.1) |
| Module Access | `/superadmin/modules` | Mocked, schema gap | `tenant_module_access` table TBD |
| Guardrails | `/superadmin/guardrails` | Mocked, schema gap | guardrails + approvals tables TBD |
| Audit Log | `/superadmin/audit` | Mocked | `audit_logs` (backend Step 6.2) |

Implied surfaces (auth, profile, notifications, approvals inbox, impersonation banner) all scaffolded structurally in v0. Auth screens deferred to Auth0 landing.

---

## Repository layout (target)

```
admin-frontend/
├── app/                          # Next.js App Router
│   ├── (auth)/
│   │   ├── login/
│   │   ├── forgot-password/
│   │   ├── accept-invite/[token]/
│   │   └── mfa/
│   ├── (dev)/
│   │   └── login/                # Persona switcher
│   ├── superadmin/
│   │   ├── dashboard/
│   │   ├── tenants/
│   │   ├── org/
│   │   ├── users/
│   │   ├── roles/
│   │   ├── modules/
│   │   ├── guardrails/
│   │   └── audit/
│   ├── profile/
│   ├── notifications/
│   ├── approvals/
│   ├── layout.tsx                # Root layout, providers
│   └── globals.css
├── components/
│   ├── ui/                       # shadcn/ui primitives
│   ├── chrome/                   # Sidebar, top bar, impersonation banner
│   ├── tenants/
│   ├── org/
│   ├── users/
│   ├── roles/
│   ├── modules/
│   ├── guardrails/
│   ├── audit/
│   └── shared/                   # Empty states, skeletons, dialogs
├── lib/
│   ├── api/                      # Typed fetch clients per resource
│   ├── hooks/                    # TanStack Query hooks
│   ├── auth/                     # Auth0 wrapper + stub persona logic
│   └── utils/
├── mocks/
│   ├── config.ts                 # Per-endpoint mock|real toggle
│   ├── handlers/                 # MSW handlers per resource
│   └── fixtures/                 # Static data, derived from backend seed
├── types/
│   └── api.ts                    # Generated from OpenAPI when available
├── public/
├── BUILD_PLAN.md
├── README.md
├── package.json
├── pnpm-lock.yaml
├── tsconfig.json
├── tailwind.config.ts
└── next.config.js
```

---

## Environment variables

```
NEXT_PUBLIC_API_BASE_URL         # empty in dev (same-origin; MSW intercepts); flip to backend host in Phase 4
NEXT_PUBLIC_AUTH_MODE             # "stub" | "auth0"
NEXT_PUBLIC_AUTH0_DOMAIN          # required when AUTH_MODE=auth0
NEXT_PUBLIC_AUTH0_CLIENT_ID       # required when AUTH_MODE=auth0
AUTH0_CLIENT_SECRET               # server-only, required when AUTH_MODE=auth0
AUTH0_SECRET                      # server-only, session encryption
NEXT_PUBLIC_REGION                # "US" | "EU"
NEXT_PUBLIC_DEMO_MODE              # "true" surfaces Reset demo data button on audit log
```

---

## Open questions deferred to wiring phase

Things the design spec leaves open that don't block v0 shell but need answers when wiring lands:

- Tenant statuses: confirm `archived` is or isn't a valid terminal state
- Multi-tenant user assignment: one tenant per user, or many?
- Custom roles: tenant-scoped only, or can platform-scope custom roles exist?
- Date range filter defaults on audit log
- CSV export row caps
- Per-region routing strategy for cross-region staff access
- WebAuthn as a second MFA factor

These don't block the v0 shell; they're tracked here so they don't get lost.

---

## Cross-references

- Backend repo: `/home/zorin/ithina-retail/admin-backend` (different WSL user, separate repo)
- Backend lead: Sanjeev
- Frontend lead: Neerj (this repo)
- Communication shape between repos: HTTP only, no shared filesystem, no shared types until OpenAPI generation lands

---

## Status

v0 build not yet started. See `BUILD_PLAN.md` for step list.
