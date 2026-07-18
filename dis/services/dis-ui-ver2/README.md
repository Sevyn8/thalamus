# services/dis-ui-ver2 (foundation)

A standalone parallel frontend SPA for DIS, scaffolded alongside `services/dis-ui`.
Vite + React + TypeScript, Tailwind v4, react-router 7, TanStack Query 5, Vitest +
React Testing Library. Like `dis-ui`, it is a self-contained pnpm project (its own
`package.json`, `pnpm-lock.yaml`, and `node_modules`; no repo-level pnpm workspace)
and, when built out, talks only to `dis-ui-server`.

**Status.** Minimal working shell only: router + TanStack Query provider + one
protected placeholder route, behind the same dev-login stub-auth flow as `dis-ui`.
The product screens are not ported here yet.

**Relationship to `services/dis-ui`.** This service mirrors dis-ui's stack, config
shapes (tsconfig / tailwind / eslint / vitest setup), auth token handling, and
dis-ui-server type mechanism. Nothing is shared as a package: needed pieces are
copied/adapted locally (no premature abstraction). The single source of truth for
the backend contract stays the contract doc (`docs/dis-ui-server-contract.md`, copied
here) plus `docs/architecture.md` 4.17 and `docs/decisions.md`.

**Auth (dev).** Token handling is copied byte-for-byte from `services/dis-ui/src/auth`:
an HMAC-signed stub JWT (HS256, issuer `https://customer-master.local`, audience
`dis`), verified by `src/auth/verifyToken.ts` (the single JWKS swap seam for real
Customer Master, decisions.md D25). `/dev/login` logs a persona in with a pre-supplied
`VITE_STUB_TOKEN_*` token; everything under `AuthBoundary` requires a valid token.

**Types / backend.** `src/lib/dis-ui-server/` mirrors dis-ui's hand-written type
mechanism (no codegen): per-endpoint module + fixtures + `mode.ts` fixture/real switch.
Fixtures are shaped to the eventual contract with `OPEN`/`PROVISIONAL` comments; the
real branch throws loudly. No MSW, no mocks.

## Known deferred (auth)

The auth layer was copied **verbatim** from `services/dis-ui/src/auth`, so it inherits
that service's current auth debt. **This shell is NOT real-backend-viable as-is** and
must be migrated before the first real read or write surface lands:

- **Pre-Slice-17b claim set.** Frontend-minted dev tokens (personas via
  `signStubToken`) carry **no `user_type`** claim. `dis-ui-server` has required
  `user_type` (`TENANT`/`PLATFORM`) since Slice 17b (D91/D92) and rejects a token
  without it with `bad_claims`. So v2's own dev-login tokens are refused by the backend.
- **HS256 dev-stub vs RS256/JWKS backend.** `verifyToken.ts` verifies an HS256 stub
  token against a hard-coded dev secret. The deployed `dis-ui-server` has already moved
  to **RS256/JWKS** (the D25/13b swap) with an env-configured issuer/audience and key
  pair, so no HS256 stub token verifies against it.
- **Legacy persona identities.** `personas.ts` / `ME_FIXTURES` use legacy slice-2
  external ids (`u_acmeuser0001`, tenant_id `t_acme9k2l1mn4`, ops sub `anjali`), **not**
  the real dev-90d token identities (auth0 subs e.g. `auth0|ccf3a17156dc8907`, cloud
  **UUID** `tenant_id` e.g. `019df261-b87c-7d3e-ab9e-dcf26259cec6`, and a `user_type`
  claim). Ties to open **D37** (external id vs UUID `tenant_id` translation).
- **No real-mode verify branch.** `verifyToken.ts` has no `real` path: it verifies with
  the **public HMAC secret even when `VITE_DIS_UI_SERVER_MODE=real`**. Frontend auth is
  advisory only; real security depends entirely on backend token verification.
- **Dev artifacts in the prod bundle.** `/dev/login` and the dev secret value ship in
  the production build (`verifyToken.ts` imports `devStubSecret.ts`, and the route is
  registered unconditionally). The `signStubToken` minter is correctly tree-shaken out.

Migration (before any real backend call): swap `verifyToken.ts` to Customer Master
JWKS/RS256 verification, emit `user_type` (and, for PLATFORM impersonation writes,
`acting_for_tenant_id` in the request body), replace persona/fixture identities with the
real auth0-sub / UUID-tenant model, and gate or remove `/dev/login` + the dev secret from
production builds.

**Quick start (from `services/dis-ui-ver2/`).**
- `pnpm install`
- `pnpm dev` - dev server (Vite default port 5173)
- `pnpm test` - Vitest
- `pnpm build` - production bundle
- `pnpm lint` / `pnpm tsc` - ESLint / strict type-check

**Running the local smoke (dev-login against a real backend).**
Pass the per-persona dev-stub tokens on the SHELL, not via `.env.local`:

```
VITE_STUB_TOKEN_TENANT=<tenant-token> \
VITE_STUB_TOKEN_OPS=<ops-token> \
VITE_STUB_TOKEN_BUCEES=<second-tenant-token> \
VITE_DEV_PROXY_TARGET=http://localhost:8090 \
pnpm dev
```

Then open `/dev/login` and pick a persona. Vite exposes `VITE_`-prefixed shell env
as `import.meta.env.VITE_*`, so dev-login resolves the baked token exactly as in a
built image. Mint tokens with the signer in `src/auth/dev/signStubToken.ts` (or the
repo's `scripts/jwt/gen_dis_jwt_90d_v1.sh` for backend-valid tokens carrying
`user_type`).

Do NOT put `VITE_STUB_TOKEN_*` in `.env.local`. Vitest loads `.env.local` and Vite
inlines the literal `import.meta.env.VITE_STUB_TOKEN_*` values at transform, which
`vi.stubEnv` cannot override, breaking `DevLogin.test.tsx`. Keeping the tokens on the
shell keeps the test suite deterministic (15/15) whether or not a smoke is running.

**Container build.** `terraform/docker/dis-ui-ver2.Dockerfile` +
`terraform/docker/cloudbuild-dis-ui-ver2.yaml` (build config only; not deployed),
mirroring the dis-ui pattern: two-stage node:22 build -> nginx serve, SPA fallback,
`/api` proxied to dis-ui-server via a runtime `DIS_UI_SERVER_BASE_URL` env.

**Directory structure.**
```
services/dis-ui-ver2/
├── README.md
├── .env.example
├── index.html
├── package.json
├── vite.config.ts
├── eslint.config.js
├── tsconfig*.json
├── docs/
│   └── dis-ui-server-contract.md   # the dis-ui-server contract (copied from dis-ui)
└── src/
    ├── App.tsx               # QueryClientProvider + AuthProvider + BrowserRouter
    ├── main.tsx
    ├── index.css             # @import "tailwindcss"
    ├── auth/                 # copied verbatim from dis-ui: AuthSnapshot, AuthProvider/
    │   │                     #   context/useAuth, AuthBoundary, verifyToken, storage
    │   └── dev/              # stub-JWT secret, personas, signStubToken (dev only)
    ├── lib/
    │   ├── queryClient.ts
    │   └── dis-ui-server/    # types, mode, fixtures, me (getMe + useMe)
    ├── routes/               # AppRoutes, DevLogin, Placeholder
    └── test/                 # setup.ts (jsdom realm fix), renderWithProviders
```
