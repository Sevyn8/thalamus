# Thalamus Security Posture

This document describes the security controls that exist today, including the
known weak points, so operators reason from facts. Nothing here is aspirational.

## Network and invoker posture

- **Publicly invokable** (Cloud Run `allUsers` invoker, all ingress):
  cm-backend, cm-frontend, dis-ui-server, dis-ui-ver2. For these, the verified
  Auth0 JWT is the **sole** gate on every API request.
- synapse-ui-server allows no anonymous access: its invoker binding is IAM-only
  (the platform caller's service account). However, cm-frontend and dis-ui-ver2
  run as the **default compute service account**, so the binding admits that
  broad shared identity rather than one dedicated caller.
- axon-sender has `INTERNAL_ONLY` ingress and serves only `/healthz`; it has no
  invoker binding at all.

## Authentication

- Every API service verifies Auth0-issued RS256 JWTs against the tenant's JWKS,
  checking signature, expiry, issuer, and audience:
  - cm-backend: `admin_backend/auth/auth0.py` (issuer/audience from settings).
  - dis-ui-server: `dis_ui_server/auth/` — `DIS_AUTH_MODE=AUTH0` is the
    default. `STUB` (HS256, fixed dev secret) refuses to start unless
    `POSTGRES_URL` points at a local TCP host, so the stub verifier cannot be
    enabled against the staging database.
  - synapse-ui-server: PLATFORM-only routes decided by the `user_type` claim.
  - cm-frontend uses `@auth0/nextjs-auth0` (session on the server);
    dis-ui-ver2 is an Auth0 SPA (`@auth0/auth0-react`) whose bearer token is
    forwarded to dis-ui-server through the nginx `/api` proxy.
- Claims contract: an Auth0 Action stamps `https://sevyn8.com/user_type`
  (`PLATFORM` or `TENANT`) and the tenant identity. `user_type` is explicit and
  validated at verification — never derived from `tenant_id` presence. A TENANT
  identity always carries a `tenant_id`; a PLATFORM identity carries none from
  the token.

## Authorization

- cm-backend: permission-tuple RBAC (`require(<module>, <resource>, <action>,
  <scope>)` dependencies over role assignments anchored in the org tree), with
  PLATFORM and TENANT audiences. Invalid or insufficient grants map to typed
  errors (`PERMISSION_DENIED`, 403/404 per RLS).
- dis-ui-server: scope dependencies (`require_read_scope`, `require_write_scope`,
  `require_tenant`, `require_super_admin`) over the verified identity; PLATFORM
  callers may act for a tenant only through the explicit request-supplied
  acted-for path (a controlled exception to tenant-from-token).
- synapse-ui-server: one discriminator — `user_type=PLATFORM` — by design (no
  second role claim will be added as a parallel gate). Its one write-adjacent
  route (enable) additionally delegates to cm-backend
  `GET /api/v1/me/can-do` (`ADMIN.TENANTS.CONFIGURE.GLOBAL`) and fails closed.

## Tenant isolation (RLS)

- Tenant context reaches PostgreSQL exclusively as two transaction-local GUCs
  set via `set_config(..., is_local=>true)`: `app.tenant_id` and
  `app.user_type`. TENANT sessions are pinned to one tenant; PLATFORM sessions
  with a NULL tenant see everything and (by grant) write nothing; PLATFORM with
  a concrete tenant is impersonation via the gated acted-for path.
- Tenant-scoped tables in every plane carry `ENABLE` + `FORCE ROW LEVEL
  SECURITY` with a `tenant_isolation` policy on
  `current_setting('app.tenant_id', true)`; FORCE applies to the table owner
  too. `identity_mirror.*` is deliberately RLS-off (platform reference data).
- Fail-closed properties:
  - With no GUC set, RLS-protected reads return **zero rows silently** — not an
    error. Hand-run SQL must set the GUCs first; this is the standing
    silent-zero trap.
  - All application roles are `NOSUPERUSER NOBYPASSRLS`, and both the CM and
    DIS engines assert NOBYPASSRLS plus the expected database at first use
    (`dis_rls/session.py`, cm-backend `db/engine.py`), so a mis-wired DSN fails
    loudly instead of bypassing policy.
  - Every DIS write to canonical/bronze/quarantine/audit tables must run inside
    a `dis_rls` session; `dis_rls.enforcement` raises on a write outside one.
- Database roles are one-per-plane with minimal verbs (see ARCHITECTURE.md).
  Notable: `synapse_writer` is INSERT-only with no SELECT ("resolvers never
  write" is a grant property, not a convention), and synapse-ui-server has no
  writer DSN in its config at all — `SYNAPSE_WRITER_URL` in its environment is
  a startup failure.

## Service-to-service trust

- cm-frontend → synapse-ui-server: Google ID token minted from the metadata
  server; the browser never reaches synapse-ui-server.
- synapse-ui-server → cm-backend: the can-do authorization call (fail-closed).
- Pub/Sub consumers trust the message envelope's already-resolved identity and
  mint no identity of their own; connector jobs trust the trigger arguments
  (tenant/store/source/template) supplied at `gcloud run jobs execute` time.
  Whoever can publish to a topic or execute a job speaks with that identity.
- dis-ui-ver2's nginx proxies `/api` to dis-ui-server, passing the user's JWT
  through; the proxy adds no credential of its own.

## Secrets

- Secret Manager holds DB role passwords, Auth0 client secrets, the SendGrid
  key, and the Square/Clover OAuth tokens (vault token store). Access is per
  service account via `secretAccessor` bindings in the Terraform modules.
- Weak point: cm-frontend and dis-ui-ver2 run as the **default compute service
  account**, which holds `secretAccessor` on real credentials — the frontends'
  identity is not least-privilege.
- cm-backend's local stub-auth flow uses an RS256 development keypair under
  `cm-backend/keys/` — **local, git-ignored material** (`keys/` and `*.pem`
  are in `cm-backend/.gitignore`; nothing under `keys/` is tracked). It exists
  only on developer machines and must never be reused for anything real.
  CI generates a throwaway keypair per run rather than consuming one.
- Secret scanning is a **blocking** pull-request gate (`security-secrets` in
  `.github/workflows/ci.yml`): gitleaks over full history, configured by
  `.gitleaks.toml`. Every pre-existing finding was triaged individually and is
  recorded there with the reason it is not a credential; none was a production
  credential. A new finding fails the PR — rotate the value, do not allowlist it.
- Dependency and IaC vulnerability scanning runs in **reporting mode only**
  (`supply-chain-report`), because untriaged historical findings exist today:
  61 npm advisories in cm-frontend (2 critical, 24 high), 21 in dis-ui-ver2, and
  12 HIGH Terraform misconfigurations. This is a known gap, not a clean bill of
  health; the job exists so the numbers are visible and cannot quietly grow.

## PII

- The PII gate is fail-loud and runs before any bronze write: if the detector
  flags PII-designated columns and no handling backend is configured,
  `assert_pii_handled` raises `PiiBackendNotConfiguredError` and the file is
  refused (csv-ingest-worker `pii_gate`, connector SDK pipeline). No
  tokenization/KMS backend exists; the gate's job is to refuse, not to handle.
- Detection is a bounded column-name heuristic (phone, email, loyalty, PAN,
  Aadhaar, plus tenant-policy fields) — bounded coverage with known false
  negatives; it is a backstop, not a guarantee.
- Mapping/quarantine/audit paths log counts, keys, and column names — never
  cell values.

## Object storage isolation

Bronze GCS object paths use the **internal tenant UUID** as the tenant segment
(`tenant/{tenant_uuid}/source/{source_id}/yyyy=/mm=/dd=/{trace_id}.{ext}`) —
never an externally editable tenant code — so path-scoped access cannot be
steered by renaming a tenant. Signed upload URLs are scoped to exactly one
object path and expire in about 15 minutes.

## Development-only surfaces

- dis docker-compose runs `identity-service-fake`; dis-ui-ver2 ships dev
  personas and a runtime stub-token mint used only in stub mode; cm-backend has
  a `StubAuthClient` (RS256, verifying against a local git-ignored dev
  keypair; `make_test_jwt` signs with the same keypair) selected by settings.
- Gating is by environment configuration: the staging Terraform wires AUTH0
  mode and real DSNs. dis-ui-server's STUB mode additionally refuses non-local
  databases (see above); the other stub surfaces have no equivalent structural
  guard beyond configuration.

## Known gaps (facts, tracked outside this doc)

- Auth0 JWT is the only barrier on four publicly invokable services.
- The frontends' shared default-compute identity (invoker + secret access).
- mirror-sync's "never read from the write target" guard (`DIS_DB_NAME`)
  is inert now that CM and DIS share one database — it can no longer
  distinguish the two.
