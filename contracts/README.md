# Cortex v3 contracts

The shared, tiny, language-neutral contracts repo (architecture-spec section 4).
It holds the interface definitions that Cortex (TS), DIS (Python),
and Customer Master must all agree on. Schemas and written specs only: no
service, no loader, no implementation. Implementations conform to these
contracts; they are not authored here.

Contracts change only at gate boundaries (architecture-spec section 3); mid-phase
needs are logged and stubbed around.

## Branch protection

Branch protection on this repo is deliberately deferred for now. The current unprotected-merge
behavior is intentional and recorded here, not an oversight; it is revisited when
signing becomes load-bearing (see `registry/registry-v0-deferred.md`, D3/D4).

## The six contracts

| Code | Contract | Path | Status |
| --- | --- | --- | --- |
| C1 | Machine-auth token (claims, scopes, validation) | — | not yet authored |
| C2 | Spine event schemas (versioned per event type) | — | not yet authored |
| C3 | Action ledger API (propose, query state) | — | not yet authored |
| C4 | Merge semantics API (resolution proposes, CM adjudicates) | — | not yet authored |
| C5 | Consent query API | — | not yet authored |
| C6 | Pack contract (structure, SemVer, engine-compat, signing) | `pack/` | authored |

Only C6 is authored. Each unauthored contract gets its own top-level directory
when it is authored; the layout is intentionally flat so each contract can
version on its own cadence.

## C6 pack contract (this repo's first content)

`pack/` defines the language-neutral Atlas pack artifact format: a signed
manifest plus typed payload sections. A Python-extracted (DIS) pack and a
TS-authored (Cortex) pack emit the same artifact. See `pack/README.md`.

## Scope guard (read before extending the pack payload)

Date tokens and quarantine RULES are engine-global in v3 today, NOT per-vertical.
They are deliberately absent from the pack payload schema. A pack may reference
validation and quarantine suites (`validation_quarantine_refs`); it must not
embed the date-token table or quarantine rule bodies. The payload schema is
closed (`additionalProperties: false`) so a producer that tries to ship
`date_tokens` or `quarantine_rules` is rejected. This keeps the retail
extraction from over-reaching.

## Pack version vs other versions (do not conflate)

Three different numbers exist; the loader must not conflate them:

- Pack `version` (manifest, SemVer): the version of the whole pack artifact.
- DIS `mapping_version_id` (DB BIGSERIAL): row-level lineage in the DIS
  `config.source_mappings` table, stamped on canonical rows for replay. Not a
  pack version.
- `version` (int) inside a `mapping_rules` set: the version of one mapping rule
  set within the pack. Not the pack version.

## Conformance

`conformance/validate.py` validates the example packs against the schemas,
verifies content digests, and runs the negative and scope-guard cases. It needs
only Python and `jsonschema`. Run: `python3 conformance/validate.py`.
