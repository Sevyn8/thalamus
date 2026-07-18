# Prompt — Step 1.2: Auth scaffolding (stub mode)

> Paste this after Step 1.1 is committed.

---

## Pre-flight

```bash
pwd                              # /home/neerj/projects/admin-frontend
git log --oneline -5             # confirm Step 1.1 commit is at top
pnpm dev                         # in another terminal: confirm dev server runs
pnpm tsc --noEmit                # must exit zero before starting
```

If `pnpm tsc --noEmit` fails, STOP and tell the user. The previous step left things in a bad state.

Read `BUILD_PLAN.md` Step 1.2 in full. Read `README.md` sections "Auth during build phase" and "API contract (locked for v0)" before writing any code.

---

## Step ID and intent

**Step 1.2** — Auth scaffolding in stub mode. Persona switcher works; tokens flow through to the API client (which doesn't exist yet — create the auth layer such that 1.3 can plug into it).

This is a CLAUDE_CODE step. No real Auth0 calls; everything runs on stub-minted RS256 JWTs in dev.

---

## Scope in

### 1. Generate a dev RS256 keypair

The frontend mints stub JWTs locally for dev personas. Backend's stub auth client must be configurable to verify with the same public key (Sanjeev will handle the backend side; you produce the public key file for him).

```bash
mkdir -p keys
openssl genrsa -out keys/dev-private.pem 2048
openssl rsa -in keys/dev-private.pem -pubout -out keys/dev-public.pem
```

Add `keys/` to `.gitignore`. The keypair is dev-only; don't commit it.

### 2. JWT claim shape

JWTs MUST match the backend's expected claim shape exactly. From `architecture.md`:

```json
{
  "iss": "https://ithina.auth0.com/",
  "aud": "https://api.ithina.com",
  "sub": "auth0|<persona-id>",
  "iat": <unix-seconds>,
  "exp": <unix-seconds + 3600>,
  "https://ithina.com/tenant_id": "<uuid>" | null,
  "https://ithina.com/user_type": "PLATFORM" | "TENANT",
  "https://ithina.com/user_id": "<uuid>",
  "https://ithina.com/roles": ["string"]
}
```

Use the `jose` library (already installed) to sign tokens with RS256.

### 3. Persona fixtures

Create `lib/auth/personas.ts`:

```typescript
export type Persona = {
  id: string;                      // UUID, used as user_id claim
  authSubject: string;             // sub claim, e.g. "auth0|anjali-mehta"
  name: string;
  email: string;
  userType: "PLATFORM" | "TENANT";
  tenantId: string | null;         // UUID for TENANT, null for PLATFORM
  tenantName: string | null;       // display only
  roles: string[];                 // role codes, e.g. ["SUPER_ADMIN"]
};

export const PERSONAS: Persona[] = [
  {
    id: "00000000-0000-4000-8000-000000000001",
    authSubject: "auth0|anjali-mehta",
    name: "Anjali Mehta",
    email: "anjali@ithina.ai",
    userType: "PLATFORM",
    tenantId: null,
    tenantName: null,
    roles: ["SUPER_ADMIN"],
  },
  {
    id: "00000000-0000-4000-8000-000000000002",
    authSubject: "auth0|marcus-tanner",
    name: "Marcus Tanner",
    email: "marcus@bucees.com",
    userType: "TENANT",
    tenantId: "a1b2c3d4-0003-4000-8000-000000000003", // Buc-ee's, matches frontend dev contract example
    tenantName: "Buc-ee's",
    roles: ["OWNER"],
  },
  {
    id: "00000000-0000-4000-8000-000000000003",
    authSubject: "auth0|kira-yilmaz",
    name: "Kira Yilmaz",
    email: "kira@ithina.ai",
    userType: "PLATFORM",
    tenantId: null,
    tenantName: null,
    roles: ["SUPPORT_ADMIN"],
  },
];
```

### 4. JWT minting

Create `lib/auth/mint.ts`:

```typescript
// Given a persona, return a signed RS256 JWT matching backend claim shape.
// Reads private key from keys/dev-private.pem (server-side only).
// Token TTL: 1 hour.
```

This must run server-side only (key file access). Use a Next.js Route Handler at `app/api/dev/mint-token/route.ts` that takes a persona ID via POST body and returns the signed JWT. Reject if `NEXT_PUBLIC_AUTH_MODE !== "stub"`.

### 5. Auth client wrapper

Create `lib/auth/client.ts`:

```typescript
// Public surface used by the rest of the app:
//   getToken(): Promise<string | null>
//   getCurrentUser(): Promise<Persona | null>
//   logout(): Promise<void>
//
// In stub mode, reads token from cookie set by /dev/login.
// In auth0 mode, delegates to @auth0/nextjs-auth0 SDK.
// Mode is selected by NEXT_PUBLIC_AUTH_MODE env var.
```

Token storage in stub mode: HttpOnly cookie `__ithina_dev_token`, `SameSite=Lax`, `Secure` only in prod, max-age 3600.

### 6. /dev/login persona switcher page

Create `app/(dev)/login/page.tsx`. Renders 3 persona cards (Anjali, Marcus, Kira) using shadcn `Card`. Each card shows name, email, role, tenant. Click a card → POST to `/api/dev/mint-token` with persona ID → set cookie → redirect to `/superadmin/dashboard`.

Style: simple, dev-only, doesn't need to match prototype polish. Add a banner at the top reading "DEV LOGIN — stub auth mode. Personas only available when NEXT_PUBLIC_AUTH_MODE=stub."

If `NEXT_PUBLIC_AUTH_MODE !== "stub"`, the page renders a notice ("Auth0 is configured. Use the production login flow.") instead of personas.

### 7. Middleware for route protection

Create `middleware.ts` at the repo root:

```typescript
// Protect /superadmin/*
// In stub mode: check for __ithina_dev_token cookie; redirect to /dev/login if absent.
// In auth0 mode: delegate to @auth0/nextjs-auth0 middleware.
```

Public routes (no auth required): `/dev/*`, `/login`, `/forgot-password`, `/accept-invite/*`, `/mfa/*`, `/api/dev/*`, `/_next/*`.

### 8. Default landing redirect

Visiting `/` should redirect to `/superadmin/dashboard` if authenticated, otherwise to `/dev/login` (in stub mode) or `/login` (in auth0 mode).

Use `app/page.tsx` with a server-side redirect.

### 9. Empty placeholder for /superadmin/dashboard

Create `app/superadmin/dashboard/page.tsx` with a minimal placeholder (just "Dashboard" heading and the current persona's name pulled from JWT). Don't build the real dashboard yet — that's Step 2.1. This step just needs the route to exist so the auth flow has a destination.

### 10. Public-key file for Sanjeev

After generating the keypair, write the public key path and shape to a note for the user to share with Sanjeev:

```
keys/dev-public.pem  -- public key file
JWT_PUBLIC_KEY_PATH=/path/to/keys/dev-public.pem  -- env var Sanjeev sets on backend
JWT_ISSUER=https://ithina.auth0.com/
JWT_AUDIENCE=https://api.ithina.com
```

Surface this in your final report so the user knows what to share.

---

## Scope out

- No real Auth0 integration (stub mode only)
- No MFA flow, no forgot-password, no accept-invite (those are Phase 3 surfaces)
- No actual `/superadmin` chrome (that's Step 1.4)
- No API client (that's Step 1.3)
- No persistent token store beyond cookie

---

## Acceptance criteria

1. `keys/dev-private.pem` and `keys/dev-public.pem` exist; `keys/` is in `.gitignore`
2. `lib/auth/personas.ts` defines the 3 personas with the exact UUIDs above
3. `POST /api/dev/mint-token` with `{personaId: "..."}` returns a valid RS256 JWT
4. The returned JWT, decoded, contains all 4 custom claims with correct values for the persona
5. `/dev/login` renders 3 persona cards in stub mode; clicking one sets cookie and redirects to `/superadmin/dashboard`
6. Visiting `/superadmin/dashboard` without the cookie redirects to `/dev/login`
7. `/superadmin/dashboard` placeholder shows "Dashboard" + current persona's name
8. `pnpm tsc --noEmit` exits zero
9. `pnpm dev` runs without errors; full flow exercised by you in the browser
10. `BUILD_PLAN.md` Step 1.2 flipped to DONE

---

## After completing the step

1. Confirm acceptance
2. Report:
   - Files added (with line counts)
   - Public key path and JWT issuer/audience values for Sanjeev (call this out clearly)
   - Any decisions made on your own
3. Update BUILD_PLAN.md
4. Propose commit:
   ```
   git add -A
   git commit -m "Step 1.2: stub auth + persona switcher"
   ```
5. Wait for user direction before Step 1.3

---

## If you hit a snag

- jose API uncertain: check the version installed, read its README on disk, do not invent API. Mark `verified` only after testing.
- RS256 sign/verify roundtrip fails locally: stop, ask the user. The whole auth chain depends on this working.
- Middleware location confusion (App Router has specific rules): refer to Next.js docs, don't guess. The `middleware.ts` file lives at the project root, not in `app/`.
- Next.js cookie API differs between server actions, route handlers, and middleware: use the right one for the context. Verify by testing.
