# DIS Legacy Archive — 2026-06-01

This tree is **frozen**. It was active code in `admin-frontend` until Phase
5i.3b moved it here. Nothing under `archive/dis-legacy/` is imported,
compiled, or deployed. Git history is preserved per-file via `git mv`.

---

## 1. Reason for archive

The DIS surfaces in this directory were built against three assumptions
that no longer hold:

1. **A DIS backend exists at `/api/v1/dis/*` on the admin-backend service.**
   It does not. The 40 distinct endpoints these surfaces call return 404
   on the deployed `admin-backend` (audited 2026-06-01 against v0.1.23).
   The frontend was built MSW-only; Phase 5n.1 (2026-05-18) removed MSW
   wholesale, so these surfaces now hit nothing.

2. **DIS UI shares Ithina's auth boundary** — Persona JWT, `AuthBoundary`,
   `userType` checks for `PLATFORM`/`TENANT`. Per Sanjeev's locked DIS
   architecture (D25, D26), DIS UI authenticates against **Customer
   Master**, a separate identity system. The existing surfaces would need
   every auth check rewritten to migrate; a separate app is the cleaner
   path.

3. **DIS UI lives alongside Ithina admin in `admin-frontend`.** Per
   Sanjeev's `repo-structure.md`, DIS UI lives in a separate `ithina-dis`
   monorepo at `ithina-dis/ui/` and talks to `dis-api` (BFF). The two
   products no longer share a codebase.

Audit reference: Phase 5i.3a (commit on phase-5f-local, 2026-06-01).
Archive execution: Phase 5i.3b.

---

## 2. Sanjeev's locked DIS architecture docs (NOT vendored here)

The authoritative DIS planning lives in the `ithina-dis` repository when
that exists. Referenced by filename only; this archive does NOT duplicate
their content:

- `architecture.md` — overall DIS architecture, service boundaries
- `decisions.md` — D1–D33 decision log (D25/D26 establish the
  Customer Master auth boundary and ithina-dis/ui separation)
- `build-guide.md` — build sequence for the rebuild
- `repo-structure.md` — `ithina-dis/{api,ui,worker,...}` layout
- `engineering-reference.md` — implementation reference
- `cost-estimate.md` — infra cost model

When `ithina-dis` exists, those docs supersede everything in this
archive's `docs/` subdirectory.

---

## 3. Bucket mapping (from 5i.3a audit §2)

Surfaces grouped by overlap with Sanjeev's planned DIS UI sub-modules
(Auth via Customer Master / Sample upload / Onboarding review /
Mapping CRUD / Quarantine console / Audit-trace lookup / DuckDB panel).

| Bucket | Meaning | Surfaces in this archive |
|---|---|---|
| **A** ALIGNED | Direct UX parallel; mine for rebuild | Uploads (drop-zone → sample rows → mapping review); Canonical Schema (domain → entity → field registry, version-bump, soft-delete, audit panel) |
| **B** ADJACENT | Concept overlaps but scope differs | Sources / Streams (catalogue model); Add-Source / Add-Stream / Add-Super-Template wizards; Templates (super-template bundles); Validation (rules + drift); Runs (RunDetailHeader, RunErrorPanel); Admin AuditPanel |
| **C** ORPHAN | No parallel in Sanjeev's locked scope | Backfills; Alerts (events + rules); Freshness; Admin Fleet / LLM-ops / Cost; Changelog / Status / Settings / Docs / Dashboards |

---

## 4. UX patterns to harvest for `ithina-dis/ui/`

Worth carrying forward verbatim:

- **Uploads flow** (`components/dis/uploads/`): drop-zone → CSV parse
  via `lib/dis/csv-parser.ts` → `SampleRowsTable` preview →
  `MappingReviewView` per-column suggested-mapping with confidence
  affordance + manual override → `MappingActions` toolbar. This is
  the spec for "Sample upload" + "Onboarding review".

- **Canonical schema admin model** (`components/dis/admin/`,
  `app/(dis-authenticated)/dis/canonical-schema/`): per-field
  metadata (type, PII flag, description, version), bump-version
  modal, soft-delete with audit chain, PLATFORM-only writes overlaid
  on read-for-all browse. Reusable for "Mapping CRUD" target schema.

- **Wizard step-pattern**: 5-step linear wizard with progressive
  disclosure (Type → Org Node → Name → Config → Test). Used in
  AddSourceWizard / AddStreamWizard / AddSuperTemplateWizard.

- **Connector config form taxonomy** (`components/dis/sources/wizard-steps/config-forms/`):
  6 distinct form shapes — Named POS OAuth, Shopify POS, POS API
  Generic, CSV scheduled, FTP, REST API Generic. Sanjeev's "Sample
  upload" may support a subset; the form shapes are reusable.

- **Status-chip recipe** (`components/dis/chips/`): 19 chips share
  the dark/light recipe documented in `PATTERNS.md`. Semantics will
  re-map to Sanjeev's domain vocabulary; the recipe is portable.

- **FleetPageShell** (`components/dis/shared/`): page wrapper for
  consistent header / breadcrumb / content spacing. 33 LOC; trivial
  to port.

- **Detail-view pattern**: `RunDetailHeader` + `RunErrorPanel` are
  the closest existing UX for what an "Audit-trace lookup" detail
  view needs — scoped errors, retries, timestamps.

---

## 5. Statistics

- Files archived: 181 (40 routes + 84 components + 1 chrome adapter
  + 50 lib + 2 types + 4 docs)
- LOC archived: ~16,861 (.tsx + .ts) + ~83 KB markdown docs
- Cross-references from active code: 0 after archive (the sole
  reference, `components/chrome/DisSidebar.tsx`, moved with the
  archive)
- TypeScript breakage: 0 (verified post-move)
- Active routes affected: 0 (Ithina superadmin surfaces unchanged)
- Test entanglement: 0 (no e2e or unit tests referenced DIS code)

---

## 6. How to use this archive

**For the `ithina-dis/ui/` rebuild:** mine the directories listed in
§4 for UX patterns. Folder layout here mirrors the original active
tree so pattern-matching against the rebuild's layout is direct.

**For admin-frontend contributors:** treat this tree as read-only
historical context. Do not re-import code from `archive/dis-legacy/`
into the active tree. If a pattern from here is needed in
admin-frontend (unlikely; Ithina admin and DIS UI are disjoint
scopes), copy the relevant lines rather than restoring the import
path.

**For Sanjeev / architecture reviews:** the 4 docs under
`archive/dis-legacy/docs/` (`dis-build-plan.md`,
`dis-regression-test-plan.md`, `dis-shared-components.md`,
`dis-surface-map.md`) record what admin-frontend's DIS roadmap tried
to build. They are superseded by Sanjeev's `ithina-dis` planning
docs (§2 above) but capture intent that may be useful when
sequencing the rebuild.

**Do NOT** restore any of this code to the active tree without an
explicit architecture review against the locked DIS docs in §2.
