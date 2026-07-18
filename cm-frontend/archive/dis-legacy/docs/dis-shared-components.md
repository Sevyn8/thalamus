# DIS Shared Component Reuse

**Status:** v1 (Phase 5b.3)
**Companion to:** `docs/dis-surface-map.md`, `docs/dis-build-plan.md`, `BUILD_PLAN.md`
**Owner:** Frontend planning

---

## Purpose

DIS frontend lives inside the Ithina `admin-frontend` Next.js app. Most chrome and primitives already exist for Ithina; DIS imports them rather than reinventing. This doc inventories every shared component DIS will touch, with reuse readiness and the action taken in Phase 5b.3.

Categories:

- **NO-CHANGE** — component is already generic; DIS imports unchanged. No work.
- **DOC-ONLY** — component is generic but reuse intent / shape concerns are worth flagging for future sessions. No code change.
- **REFACTOR-IN-PLACE** — minimal in-place edit (e.g., add `export`). Ithina behavior preserved exactly.
- **EXTRACT-AND-REWRITE** (deferred) — needs significant change to support DIS interaction model. Defer to a 5c chunk where the actual DIS consumer drives the API. Each deferred entry names the exact target chunk so future sessions don't re-discover.

---

## Tier 1 — Shared primitives

Already generic. DIS imports unchanged. Used in Phase 5b.1 placeholder pages already (`UnderConstruction`, `EmptyState`, `AuthBoundary`). The rest light up as DIS feature chunks (5c.1+) land.

| Component | Location | Reuse readiness | Action this chunk | DIS consumers |
|---|---|---|---|---|
| `EmptyState` | `components/shared/EmptyState.tsx` | Generic — title/body/icon/action props | NO-CHANGE | Sources/runs/uploads list empty states; canonical-schema coverage gaps; `UnderConstruction` already wraps this |
| `ErrorInline` | `components/shared/ErrorInline.tsx` | Generic — title/message/onRetry props | NO-CHANGE | Every DIS page on hook error (matches Ithina pattern) |
| `Modal` | `components/shared/Modal.tsx` | Generic — wraps shadcn Dialog | NO-CHANGE | Source create wizard, alert rule editor, channel test, etc. |
| `Drawer` | `components/shared/Drawer.tsx` | Generic — sm/md/lg width prop, footer slot | NO-CHANGE | Source detail, run detail, upload detail, alert detail (every detail-on-list pattern) |
| `Skeleton` | `components/shared/Skeleton.tsx` | Generic — variant/count props | NO-CHANGE | Loading states on every list/detail surface |
| `PageHeader` | `components/shared/PageHeader.tsx` | Generic — title/subtitle/primaryAction | NO-CHANGE | Every DIS page header |
| `ConfirmDialog` | `components/shared/ConfirmDialog.tsx` | Generic | NO-CHANGE | Acknowledge alert, cancel run, etc. (non-destructive confirmations) |
| `ConfirmDestructive` | `components/shared/ConfirmDestructive.tsx` | Generic — type-to-confirm with async loading | NO-CHANGE | Delete source, delete template, retire schema field, force-pause incident response |
| `UnderConstruction` | `components/shared/UnderConstruction.tsx` | DIS-built (Phase 5b.1) — route prop | NO-CHANGE | All 44 v1 placeholder pages until their feature chunk ships |
| `AuthBoundary` | `components/shared/AuthBoundary.tsx` | Generic — already used by both `(authenticated)` and `(dis-authenticated)` layouts | NO-CHANGE | DIS layout (Phase 5b.1) |
| `comingInV1` toast | `components/shared/ComingInV1Toast.ts` | Utility helper | NO-CHANGE | Any v1 write CTA without backend yet |
| All `components/ui/*` shadcn primitives | `components/ui/` | Generic by design | NO-CHANGE | DIS pages reach for buttons, inputs, tabs, etc. exactly like Ithina |
| `KpiCard` | `components/dashboard/KpiCard.tsx` | Generic — `icon` is `ReactNode`, `iconTone` is a literal type, no Ithina imports | NO-CHANGE | DIS dashboard widgets (ingest health, run summary, freshness scorecard, cost-this-period) — wired in Phase 5c.7 |

---

## Tier 2 — REFACTOR-IN-PLACE (this chunk)

| Component | Location | Reuse readiness | Action this chunk | DIS consumers |
|---|---|---|---|---|
| `Chip` (base) + `Tone` | `components/shared/Chips.tsx` | Was internal — needed primitive access for DIS-specific chip families | **REFACTOR-IN-PLACE**: added `export` to base `Chip` and `Tone` type. Existing 5 typed wrappers (`StatusChip`, `TierChip`, `ResultChip`, `ActionChip`, `ScopeChip`) unchanged | DIS will compose `RunStatusChip`, `SourceHealthChip`, `AlertSeverityChip`, `FreshnessStateChip`, `ValidationResultChip`, `DriftSeverityChip` etc. by importing `Chip` + `Tone` and supplying its own tone tables. Each DIS chip lives next to its consumer feature (e.g., `components/dis/sources/SourceHealthChip.tsx` from 5c.2 onward) |

**Why not extend the existing typed wrappers' enum unions instead.** `StatusChip` currently accepts `TenantStatus | PlatformUserStatus | OrgNodeStatus`. Adding DIS status enums to that union couples DIS types to Ithina's chip module and grows a single union arbitrarily. Exporting the primitive lets DIS chips live with their consumers, keeps each chip's tone table close to the domain it serves, and avoids cross-module type coupling.

---

## Tier 3 — DOC-ONLY (deferred extraction with forward pointer)

These three are shared candidates that need real refactor work, but the right shape needs a real DIS consumer driving the API. Extraction is deferred to the 5c chunk that produces that consumer. Listed here so future sessions don't re-discover the same questions.

| Component | Location | Current state | Why defer | **Forward pointer** |
|---|---|---|---|---|
| `OrgTree` family (`OrgTree`, `OrgTreeRow`, `OrgNodeTypeIcon`, `OrgNodeTypeBadge`) | `components/org/` | Browse-mode tree with lazy-load (Phase 4e) and visual indent guides (Phase 5b.2.1). `OrgTreePane` is the top-level export. Selection is component-local state and triggers `NodeDetailDrawer` side effect | Source-create wizard needs single-select picker-mode | **✅ EXTRACTED in Phase 5c.2b1** — `components/org/OrgNodePicker.tsx` is the new top-level for picker mode. Reuses `OrgTreeRow` (which gained an optional `onAction` — passing none hides the kebab dropdown) and Ithina's `useOrgTree(tenantId)` hook for data fetching. Existing `selectedId` + `onClick(node)` props on `OrgTreeRow` already carried picker semantics; no other API additions were needed. `/superadmin/org` browse-mode behavior unchanged. |
| `TenantList` | `components/org/TenantList.tsx` | Single-column nav-list of tenants. Used in `/superadmin/org` only. Props: `tenants`, `selectedId`, `onSelect`, `loading`, `hasError`, `onRetry`. Tightly shaped to the two-pane org-tree page layout | DIS admin views (`/dis/admin/fleet`, `/dis/admin/provisioning`) need tenant filtering, but probably with **search and a different shape** (dropdown or searchable command palette), not a sidebar nav-list. Extracting now risks shipping a generic that fits neither caller well | **Deferred to Phase 5c.8 (Cost, admin views, onboarding, help)** — admin-views chunk produces the first DIS consumer for tenant-filter UX; that consumer's design will pin whether `TenantList` is reusable as-is, gets a parallel `TenantPicker`, or both stay distinct |
| Inline `<select>` tenant filter | `app/(authenticated)/superadmin/users/page.tsx:149` | Native HTML `<select>` element with options injected from `useTenants()`. Never extracted to a component — local to the Users page | Same family of need as `TenantList`: DIS admin views want tenant-filter UX. Two callers in two products with no shared component is the wrong end-state. But "what does the right component look like" depends on DIS's UX choice | **Deferred to Phase 5c.8 (Cost, admin views, onboarding, help)** — co-extracted with `TenantList` review. Likely outcome: a single `TenantSelect` component (search + dropdown) with both Ithina users-page and DIS admin views as consumers; current `TenantList` stays as the org-page-specific variant |

---

## Tier 4 — Excluded (Ithina-specific, no DIS reuse path)

Listed for completeness. These components are tightly bound to Ithina-specific data shapes (`Tenant`, `PlatformUser`, `TenantUser`, `Role`, `Permission`, `Module`, `Guardrail`, audit log entries) and won't ship as shared infrastructure for DIS:

- `components/tenants/*` — `TenantCard`, `TenantDetailDrawer`, `ProvisionTenantModal`
- `components/users/*` — `PlatformUsersTable`, `TenantUsersTable`, drawers
- `components/audit/*` — `AuditTable`, `AuditDetailDrawer`
- `components/roles/*` — `RoleCatalogView`, `PermissionMatrixView`, group/row primitives
- `components/modules/*` — `ModuleSummaryCard`, `ModuleAccessMatrix`
- `components/guardrails/*` — `GuardrailRow`
- `components/profile/*` — `ProfileSecuritySection`, `ProfileNotificationPrefs`
- `components/dashboard/RecentActivityPanel`, `TopTenantsPanel` — bound to Ithina's audit log + tenants list shape

DIS will build its own equivalents (run history table, source health table, fleet health matrix, etc.) in 5c.X chunks against its own schemas.

---

## Summary

- **NO-CHANGE this chunk:** 13 entries (11 shared primitives + ui/ family + KpiCard).
- **REFACTOR-IN-PLACE this chunk:** 1 entry (`Chip` + `Tone` export from `Chips.tsx`).
- **EXTRACT-AND-REWRITE landed in Phase 5c.2b1:** OrgTree picker-mode → `components/org/OrgNodePicker.tsx`.
- **EXTRACT-AND-REWRITE still deferred:** 2 entries — TenantList/TenantSelect (→ 5c.8), inline tenant filter (→ 5c.8).
- **Excluded:** Ithina-domain-specific components.

Ithina behavior identical post-chunk. The Chip primitive is now reachable from DIS feature code without coupling DIS status enums to Ithina type modules.
