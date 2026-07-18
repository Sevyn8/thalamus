# Pack registry API surface (specification only)

Per V3-PACK-FR-005, the registry API is DEFINED here so registry v0 (signed
artifacts in GCS plus a loader in DIS) can be replaced later by a standalone
service without changing consumers. This is a written contract, not an
implementation. Registry v0 is NOT a service; it is GCS objects plus the DIS
loader, which together satisfy `fetch` and version pinning below.

## Operations

- `publish(pack_artifact)`: store a signed pack artifact under `id@version`.
  Idempotent on `id@version`; republishing the same version with different bytes
  is rejected (immutability). Requires a valid signature block per the manifest
  contract. Returns the stored coordinates and content digests.
- `list(id?, range?)`: list available `id@version` coordinates, optionally
  filtered by pack id and a SemVer range. Returns version, engine-compat, and
  signed status per entry.
- `fetch(id, version)`: return the pack artifact (manifest plus payload) for an
  exact pinned version. The consumer (DIS loader) verifies the signature and the
  per-section content digests before use; an unsigned or compat-violating or
  digest-mismatched artifact is rejected (V3-PACK-FR-003). In v0 this is a GCS
  object read by the loader.
- `yank(id, version)`: mark a version unavailable for NEW pins without deleting
  it (already-pinned tenants keep resolving so history and replay stay intact).

## Version pinning

- Tenants pin an exact pack `id@version` (V3-PACK-FR-004). Upgrades are explicit
  operations and may trigger replay (V3-RPLY).
- The registry never auto-upgrades a pinned tenant. Resolution is exact-match on
  the pinned version; `range` is used only for discovery via `list`.

## Consumer contract (loader expectations)

- Verify signature (cosign over artifact bytes) before parsing payload.
- Recompute each payload section SHA-256 and compare to `content_digests`.
- Check the engine's version against `engine_compat`; reject on violation.
- Parse payload sections with the payload schema; ignore unknown future sections
  only if the schema permits (today the payload root is closed).

## Stability

This surface changes only at gate boundaries (architecture-spec section 3). A
future standalone registry service implements exactly these operations so the
DIS loader and any second runtime (edge Cortex) need no change when v0 graduates.
