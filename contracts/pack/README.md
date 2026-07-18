# C6: Pack contract

The language-neutral Atlas pack artifact format (architecture-spec section 3
contract 6 and section 2.3; V3-PACK-FR-001 through FR-005). A pack is the
complete versioned definition of a vertical. This contract defines the artifact
SHAPE so both a Python producer/consumer (DIS) and a TS producer (Cortex) can
satisfy it. Schema and spec only: no registry service, no loader, no signing
code.

## Artifact = manifest + payload

- `pack-manifest.schema.json`: the signed, integrity-bearing header. Identity,
  SemVer version (rejects non-SemVer), engine-compat range, per-section SHA-256
  content digests, and a signature block (scheme `cosign` over the artifact
  bytes, key type `kms-keypair` for v0). The contract RECORDS the signing
  scheme; it does not sign. At skeleton stage `signed` is false.
- `pack-payload.schema.json`: the typed payload sections, each OPTIONAL at
  skeleton stage and typed when present: `canonical_schema` (neutral, JSON
  Schema or field catalog, never Pydantic or TS), `mapping_rules` (reuses the
  DIS shape: version, rename, normalize, cast, derive), `validation_quarantine_refs`
  (refs only), `kpi_definitions`, `funnel_stages` (the neutral FunnelStage
  shape), `cost_ontology`, `benchmark_values`, `scoring_rule_refs`, `model_refs`.

Field names are snake_case (matching the DIS `mapping_rules` and the funnel
shape). A TS producer normalizes its camelCase (for example `engineCompat`,
`benchmarkStepCvr`) to snake_case at serialization. This is a serialization
mapping, not a reshape of pack substance.

## Scope guard

Date tokens and quarantine RULES are engine-global in v3 today, not per-vertical.
They are intentionally NOT in the payload schema; the payload root is closed
(`additionalProperties: false`) so an over-reaching producer is rejected. Packs
reference suites via `validation_quarantine_refs`, never embed rule bodies or the
date-token table. See the `$comment` fields in `pack-payload.schema.json`.

## Registry API surface

`registry-api.md` specifies the publish, list, fetch, yank, and version-pinning
surface (V3-PACK-FR-005) as a written contract, so a future standalone service
can implement it without changing consumers. Registry v0 itself is GCS artifacts
plus a DIS loader, not a service.

## Conformance fixtures

`fixtures/retail/` and `fixtures/insurance-cac/` are two example packs that
validate green against the schemas:

- `retail` is hand-written to be representative of the DIS-extracted shape
  (field-catalog canonical schema plus DIS-shaped mapping rules).
- `insurance-cac` is derived from `Cortex/services/industry/insurance-cac`
  (TS-authored) serialized to the neutral format. It proves cross-language
  format-neutrality: a TS-authored pack is a valid neutral artifact a Python
  consumer validates.
