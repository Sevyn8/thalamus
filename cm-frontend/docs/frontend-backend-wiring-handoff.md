# Frontend ↔ Backend Wiring (Dev) — Ithina Admin Console

> **For:** Amit, integrating the Next.js frontend against the deployed admin-backend on Cloud Run.
> **Companion files:** `anjali-7d.jwt`, `a-kowalski-cloud-7d.jwt`, `openapi.json`.
> **Audience for this doc:** Amit + Claude Code working in the frontend repo. Read this fully before wiring any fetch calls; companion files are referenced throughout.

---

## 1. The wire, end-to-end

```
Browser (Next.js, deployed on Cloud Run)
    │  fetch(`${API_BASE_URL}/api/v1/...`, { Authorization: Bearer <JWT> })
    ▼
admin-backend (Cloud Run service, v0.1.2)
  https://admin-backend-f2qhpcdeba-el.a.run.app
    │  JWT verified (RS256, public key in Secret Manager)
    │  AuthContext populated → middleware → router → repo
    ▼
Cloud SQL Postgres (private IP, in-VPC)
  RLS-scoped reads (PLATFORM sees all; TENANT sees own only)
```

**Backend status:** v0.1.2 deployed in `asia-south1`. Cross-tenant isolation verified end-to-end (16/16 matrix cells, 2026-05-04). Read endpoints live; no write endpoints in v0.

**Auth posture:** Auth0 not yet configured. Until it lands, you authenticate using **two pre-minted JWTs** (provided as files). No login screen needed for dev; Auth0 swap later is a config change (see §6).

---

## 2. What you have

### 2.1 Backend URL

```
API_BASE_URL = https://admin-backend-f2qhpcdeba-el.a.run.app
```

All routes prefixed `/api/v1/`. OpenAPI spec at `${API_BASE_URL}/api/v1/openapi.json`; also provided as a static `openapi.json` file alongside this doc — **prefer the static file** for codegen/typing (it's the version this handoff was written against; live URL may drift if backend redeploys).

### 2.2 Two JWT files

| File | User type | Sees | Use for |
|---|---|---|---|
| `anjali-7d.jwt` | PLATFORM | all 7 tenants, all 25 stores, all 17 tenant_users, all 3 platform_users | platform-admin views, "everything" UI flows |
| `a-kowalski-cloud-7d.jwt` | TENANT (Żabka Group) | only Żabka data: 1 tenant, 3 stores, ~3-4 tenant_users | tenant-user UI flows, isolation testing |

Both expire in 7 days from generation. After expiry, the operator (Sanjeev) re-mints them from this repo's `scripts/jwt/generate_7d.sh` (PLATFORM users) or via inline mint with cloud-side UUIDs (TENANT users). Refresh request goes to him; this is dev-only friction.

**Each file contains exactly one JWT string** (a single line of base64-ish text starting with `eyJ...`). No JSON wrapper. Read the file content as a string and put it in the Authorization header.

### 2.3 OpenAPI spec

`openapi.json` is the contract. Use it for:
- TypeScript type generation (recommended: `openapi-typescript` or `orval`).
- Endpoint enumeration (every supported route is in there).
- Response shape (every field, including pagination envelope, is documented).

Backend response conventions worth knowing before reading the spec:
- **Lists** wrapped: `{ "items": [...], "pagination": { "total": N, "offset": 0, "limit": 20 } }`.
- **Single resources** are bare objects (no envelope).
- **Errors** always: `{ "code": "...", "message": "...", "details": null, "request_id": "..." }`.
- **Field naming:** `snake_case` throughout. JSON keys never camelCase.
- **Dates:** ISO 8601 strings.

---

## 3. The fetch pattern (recommended)

Goal: a single user-switcher in dev, with Auth0 swap being a clean replacement of the token-source later.

### 3.1 Env vars (Terraform-set on the frontend Cloud Run)

```
NEXT_PUBLIC_API_BASE_URL=https://admin-backend-f2qhpcdeba-el.a.run.app
NEXT_PUBLIC_DEV_JWT_ANJALI=eyJ...     # full content of anjali-7d.jwt
NEXT_PUBLIC_DEV_JWT_KOWALSKI=eyJ...   # full content of a-kowalski-cloud-7d.jwt
```

`NEXT_PUBLIC_*` exposes them to the browser bundle. That's intentional: in dev, the JWTs ARE the credentials and the frontend needs them. **This is acceptable only because the dev backend has fake-company seed data, no real PII.** Don't replicate this pattern when wiring against prod.

### 3.2 Auth client (single source of truth)

Wrap token retrieval in a small auth client so Auth0 swap touches one file:

```typescript
// lib/auth.ts
type DevUser = 'anjali' | 'kowalski';

const DEV_TOKENS: Record<DevUser, string> = {
  anjali: process.env.NEXT_PUBLIC_DEV_JWT_ANJALI!,
  kowalski: process.env.NEXT_PUBLIC_DEV_JWT_KOWALSKI!,
};

// Single function the rest of the app calls. Auth0 swap = replace this body.
export function getAuthToken(): string {
  const user = getCurrentUser();           // from React context / store
  return DEV_TOKENS[user];
}
```

### 3.3 API client

```typescript
// lib/api.ts
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL!;

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${getAuthToken()}` },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(`${res.status}: ${err.code ?? 'UNKNOWN'} — ${err.message}`);
  }
  return res.json();
}
```

### 3.4 User switcher (dev-only)

A simple top-right dropdown or button-pair: `[Anjali (PLATFORM) | Kowalski (TENANT)]`. Selection writes to React context / Zustand / whatever your store is. Every `apiGet` reads through `getAuthToken()`, so a switch immediately changes which user every subsequent call runs as. No auth re-handshake needed.

When Auth0 lands, this switcher disappears and `getAuthToken()` returns the Auth0 SDK's current token instead.

---

## 4. Tenants endpoints (your first integration target)

All under `/api/v1/tenants`. Three endpoints, both auth contexts work:

| Endpoint | ANJALI (PLATFORM) | KOWALSKI (TENANT) |
|---|---|---|
| `GET /api/v1/tenants` | 200, items: 7 (all tenants) | 200, items: 1 (Żabka only) |
| `GET /api/v1/tenants/{id}` | 200, any tenant | 200 for own tenant; **404** for any other |
| `GET /api/v1/tenants/stats` | 200, `{total_tenants: 7, total_stores: 25}` | 200, `{total_tenants: 1, total_stores: 3}` (RLS-scoped — see §7) |

**Cross-tenant 404 is correct.** When KOWALSKI requests Buc-ee's by ID, RLS filters the row out, backend returns 404. This is the documented behavior (decision D-17 in backend repo: RLS-blocked reads return 404, not 403, to avoid leaking row existence). Treat 404 as "either doesn't exist or you don't have access" — don't surface "forbidden" UX.

**Tenant data shape** is in `openapi.json` under `Tenant` schema. Key fields you'll likely render:
- `id`, `name`, `display_code`, `country`, `region`, `industry`, `tier`, `status`
- `monthly_revenue_usd` (string for decimal precision; nullable)
- `num_stores`, `num_users_active` (per-row aggregates)
- `modules` (array of `{code, name}` — entitled product modules)
- `created_at`, `updated_at` (ISO timestamps)

For dropdown values (tier / region / status / industry filter UI), call the lookups endpoint:

```
GET /api/v1/lookups?lists=tenant_tier,tenant_region,tenant_status,tenant_industry
```

Returns `{ "lookups": { "tenant_tier": [...], ... } }`. Each list item: `{code, display_name, display_order}`. Cache client-side per session; lookups change rarely.

---

## 5. Smoke test before debugging frontend

If a fetch call fails, **first verify the JWT works at all** via curl from your laptop. This isolates "token bad" from "frontend code bug":

```bash
JWT=$(cat anjali-7d.jwt)
curl -sS -H "Authorization: Bearer $JWT" \
  https://admin-backend-f2qhpcdeba-el.a.run.app/api/v1/tenants/stats
# Expected: {"total_tenants":7,"total_stores":25}

JWT=$(cat a-kowalski-cloud-7d.jwt)
curl -sS -H "Authorization: Bearer $JWT" \
  https://admin-backend-f2qhpcdeba-el.a.run.app/api/v1/tenants/stats
# Expected: {"total_tenants":1,"total_stores":3}
```

Different aggregates from the same endpoint = both JWTs valid, RLS working, backend healthy. If those work but frontend fetch doesn't, the bug is in your code (CORS, header format, React error boundary, etc.) — not the JWT or backend.

**Cold-start note:** The first request after a quiet period (>15 min) takes 5-15 seconds while Cloud Run scales up. Subsequent requests are <500ms. If your first integration attempt hangs for ~10s and then succeeds, that's expected — not a bug. Refresh and it'll be instant.

---

## 6. CORS

Backend's `CORS_ALLOWED_ORIGINS` was set by Terraform with the expected frontend Cloud Run URL. If your actual deployed frontend URL differs (auto-generated suffix changed, or you deploy to a different region), CORS will reject preflight (OPTIONS) requests.

**Symptom:** browser console shows `CORS error: No 'Access-Control-Allow-Origin' header` on any cross-origin fetch.

**Fix:** Send Sanjeev your actual frontend URL; he re-applies backend Terraform with the correct origin. Or as a temporary workaround, he can widen CORS to `*` for dev. Don't try to work around CORS in your frontend code — the fix belongs server-side.

---

## 7. What works, what doesn't, what's deferred

**Works in v0.1.2:**
- All `/api/v1/tenants/*`, `/api/v1/platform-users`, `/api/v1/tenant-users`, `/api/v1/lookups`, `/api/v1/health`, `/api/v1/ready`.
- Cross-tenant isolation (verified live).
- Both PLATFORM and TENANT auth contexts on all multi-user-type endpoints.

**Not in v0.1.2 (don't try to call):**
- `/api/v1/stores` — endpoint not yet shipped (Step 4.5 backlog). Will return FastAPI's default 404 (not the app's structured error envelope). If you need stores data for a UI, surface to Sanjeev; otherwise wait for Step 4.5.
- Any POST/PATCH/DELETE — v0 is read-only by design.

**Quirk worth knowing — `/api/v1/tenants/stats`:**
For TENANT users, this returns `{total_tenants: 1, total_stores: <own-tenant-count>}`. Always 1 tenant (themselves), store count varies. This is RLS-correct but the URL name implies platform-wide aggregation, which is misleading for TENANT users. Tracked as FN-AB-21 in backend; design call deferred until frontend tells backend what's actually needed. **Suggestion for your UI:** if you use this endpoint for a "platform overview" dashboard, gate the dashboard to PLATFORM users only. If you need per-tenant self-stats for TENANT users, flag to Sanjeev — backend may add a separate `/api/v1/my/stats` endpoint or lock `/tenants/stats` to PLATFORM-only based on what frontend actually wants.

**Deferred (post-Auth0):**
- Real login/logout flow.
- Token refresh (current JWTs are static 7-day; manual re-mint).
- Multi-user testing beyond the two provided JWTs.

---

## 8. Auth0 swap forward path

When Auth0 lands (no firm date; tracked as FN-AB-02 in backend repo), the swap is:

1. **Frontend installs Auth0 SDK** (`@auth0/nextjs-auth0`).
2. **`getAuthToken()` body changes** from reading env-var JWTs to calling Auth0 SDK's `getAccessTokenSilently()` or equivalent.
3. **Backend env var `AUTH_CLIENT_MODE` flips** from `STUB` to `AUTH0`. Backend already has the code path; just config.
4. **Auth0 issues JWTs with the same custom claim shape** the backend already verifies: `https://ithina.com/tenant_id`, `https://ithina.com/user_type`, `https://ithina.com/user_id`, `https://ithina.com/email`. No backend code changes.

If you build the auth client per §3.2 (single `getAuthToken()` function as the indirection point), the swap is a one-file edit on frontend + a Terraform variable flip on backend. No router changes, no fetch-pattern changes, no data-shape changes.

---

## 9. Questions / blockers → Sanjeev

- JWT expired before frontend integration is done → ask for re-mint.
- CORS error on a known-working endpoint → send him your frontend URL.
- An endpoint returns unexpected shape → check `openapi.json` first; if discrepancy, send him the curl and the actual response.
- Want a different test user (not Anjali / Kowalski) → he can mint, but the two provided cover PLATFORM and TENANT contexts which is the load-bearing distinction.
- `/api/v1/tenants/stats` posture for TENANT users — see §7; flag your UI's actual need.

---

## End of doc
