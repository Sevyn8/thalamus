# Atlas registry v0: deferred-items tracker

Suggested repo location: contracts repo, registry/registry-v0-deferred.md (or Cortex docs/spec/v3/cac/)
Companions: ../pack/ (C6 pack contract); Cortex docs/spec/v3/plan.md (Phase 1, Gate G1); DIS pre-flight report
Status: Working tracker for the registry-v0 build. Each item is parked deliberately during the loader-first sequence, with the trigger that un-parks it.

## Build order (decided)

1. DIS loader against the contracts retail fixture, read from a local path. Structure-validate (Draft 2020-12 against the two C6 schemas), verify content-digest SHA-256, check engine_compat range, map into the existing SourceMapping, reject tampered/compat-violating/unsigned-when-required. Signature verify stubbed on signature.signed. No bucket, no KMS, no extraction, no pin storage. This is the smallest verifiable result and the G1 critical path.
2. Signing + publish infra (Cortex + Terraform, after the loader).
3. Retail extraction into a real pack payload (after the loader round-trips the fixture).
4. Gate G1 prover (after a published pack).

## Deferred items

| # | Item | Why deferred | Trigger to un-park |
| --- | --- | --- | --- |
| D1 | jsonschema dev to runtime promotion | The loader needs it at runtime; it is a dev-group dep today (lock 4.26.0, already used in DIS contract tests). | Included in the first loader build turn (pyproject.toml edit plus install). |
| D2 | Pin storage: config.pack_pins table | The loader's first step reads a local fixture path, so no pin is needed yet. Decision: a distinct config.pack_pins table keyed on (tenant, source, template), NOT a column on config.source_mappings, to keep pack_version disjoint from the mapping_version_id BIGSERIAL lineage and the rules-internal version:int. | When the loader moves from local-path read to reading a tenant's pinned pack. |
| D3 | cosign signature verification (KMS key-pair) | Scheme CONFIRMED as cosign with a KMS key-pair (no longer just decided/penciled); the key-provisioning location (Cortex keyring) and the trust root remain the build detail. Net-new; no cosign or KMS pack-signing key in either repo. Loader ships with signature verify stubbed on signature.signed against signed:false fixtures. | When a KMS pack-signing key lands in Cortex's keyring and the publisher signs real packs. |
| D4 | KMS pack-signing key in Cortex keyring | Scheme CONFIRMED as KMS key-pair; the keyring location and trust root remain the build detail. Part of signing infra (build step 2); follows the cortex-gcs-key pattern in Cortex bootstrap. | Build step 2 (signing + publish infra). |
| D5 | Pack GCS bucket placement | First loader test reads a local path / GCS emulator, so no bucket decision blocks the loader. Likely a publish-side bucket in Cortex environments/shared (CMEK via cortex-gcs-key). | Build step 2, when the publisher writes artifacts. |
| D6 | CM machine identity for the loader's GCS read | v0 reads via local path / GCS emulator / the existing DIS service account; no CM 4-tuple identity required yet. | Only if pack fetch must present a CM machine identity. |
| D7 | Retail extraction into a real pack payload | The contract's retail fixture plus the in-repo sale_pos_v1.json are sufficient to build and prove the loader; the output format is already pinned by C6. Extraction is a content exercise. | After the loader round-trips the fixture (build step 3). |
| D8 | G1 replay-identity criterion (V3-RPLY-FR-003) | Gate G1 requires "replayed ingestion reproduces canonical rows identically," but true replay does not exist in DIS today (redelivery-dedup + event-time-wins upsert only; real replay is Slice 12, deferred). This is the one G1 line with an UPSTREAM CODE dependency, not an infra handshake. | Slice 12 (replay path) lands. The other three G1 criteria (boot-from-registry zero-regression, version swap, tamper rejection) are reachable without it. |
| D9 | Loader-side derive-composition type-flow enforcement for the copy and constant generators (copy output type = the referenced column's cast type; constant output type = the literal's type, so trailing normalize ops require a string intermediate) | These are structural rules that need a CROSS-SECTION reference (the source column's cast spec, or the literal's JSON type) which JSON Schema cannot express, so pack-payload.schema.json closes only the date_from_datetime arm of derive composition; the copy and constant arms must be enforced where the cross-section view exists, i.e. the DIS loader as it maps the payload into SourceMapping. | Build into the DIS loader's payload-mapping step. |

## Scope guards (do NOT pull into packs at v0)

Confirmed engine-global in DIS, must stay engine-owned, not pack content:
1. Date parsing (per-field format strings via Polars strptime; no token table).
2. Quarantine and the two-gate validation framework (libs/dis-validation).
3. Hot-projection registries (SALE_HOT_PROJECTION etc.; coupled to write-path completeness gating).
4. NORMALIZE_OPS / CastType vocab.

## Governance still open (human, not code)

1. ADR-CAC-001 and ADR-CAC-002 are Proposed; ratify at gate GR / G0.
