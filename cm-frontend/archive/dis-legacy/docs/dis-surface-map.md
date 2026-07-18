# DIS Frontend Surface Map

**Status:** Draft v1.1 (open questions resolved, threaded into page sections)
**Scope:** Full inventory (v1 + v2 + v3) with phase markers per page
**Owner:** Frontend planning
**Related:** Ithina admin-frontend (Phase 4 wiring complete for tenants, users, org-tree)

---

## Context

DIS frontend lives inside `admin-frontend` Next.js app under `/dis/...` routes, sharing chrome (header, sidebar shell, persona/JWT) with Ithina's `/superadmin/...` routes. A product-switcher dropdown in the header swaps the sidebar contents between Ithina and DIS. Sidebar component refactored to accept nav items as props before any DIS work lands.

DIS backend is a separate service (not yet deployed). Frontend will host a second API client, second OpenAPI type generation pipeline, second CORS allowlist entry. JWT issued by Ithina auth flows to DIS backend unchanged.

Both personas in v1: Anjali (Platform, fleet view across tenants) and Kowalski (Tenant, scoped to own tenant via RLS). DIS exposure to a tenant is gated on Ithina's Module Access toggle.

LLM-assist provider: Gemini (GCP-hosted, client requirement). Multi-model support designed for from admin LLM-ops onward; v1 ships with Gemini only.

---

## Phase markers

- **v1**: operational MVP. Sources, runs, validation, freshness, alerts, onboarding, single ingestion-health dashboard, plus admin-internal cost and provisioning. The minimum surface that lets a tenant ingest data and an admin operate the platform.
- **v2**: governance maturity. Warehouse zones, full catalog, schema migration, custom dashboards, SLA management depth.
- **v3**: marketplace, advanced cost controls, cross-tenant analytics, ML-feature-store adjacencies.

---

## Route tree

```
/dis
  /dashboard                                v1   (T) tenant ingestion-health summary
                                            v1   (A) fleet ingestion-health summary
  /sources                                  v1   list + create
    /sources/new                            v1   wizard
    /sources/[id]                           v1   detail
    /sources/[id]/edit                      v1
    /sources/[id]/runs                      v1   per-source run history
  /runs                                     v1   global run history (across sources)
    /runs/[id]                              v1   single run detail
    /runs/active                            v1   live in-progress
    /runs/failed                            v1   failure queue
  /uploads                                  v1   one-off CSV upload + history
    /uploads/[id]                           v1   upload detail + LLM mapping review
  /templates                                v1   tenant template library
    /templates/new                          v1   create from sample
    /templates/[id]                         v1   detail + version history
    /templates/[id]/edit                    v1
    /templates/marketplace                  v2   platform + shared tenant templates
  /canonical-schema                         v1   read-only browse (T)
                                            v1   edit (A)
    /canonical-schema/[domain]              v1   domain detail
    /canonical-schema/[domain]/[entity]     v1   entity detail
    /canonical-schema/coverage              v1   tenant coverage gap analysis
  /validation                               v1   rules registry + results
    /validation/rules/[id]                  v1
    /validation/drift                       v1   schema-drift inbox
    /validation/drift/[id]                  v1   drift event detail
  /freshness                                v1   SLA monitoring
    /freshness/breaches                     v1   breach incidents
  /alerts                                   v1   inbox
    /alerts/[id]                            v1
    /alerts/rules                           v1   rule registry
    /alerts/rules/[id]                      v1
    /alerts/channels                        v1   notification routing
  /backfills                                v1   job history + create
    /backfills/[id]                         v1
  /catalog                                  v2   dataplex passthrough browser
    /catalog/[table]                        v2
    /catalog/lineage                        v2   lineage graph
    /catalog/coverage                       v2   documentation coverage KPI
  /warehouse                                v2   zones (raw / staging / curated)
    /warehouse/[zone]                       v2
    /warehouse/[zone]/[dataset]             v2
    /warehouse/[zone]/[dataset]/[table]     v2
    /warehouse/promotions                   v2   staging→curated queue
  /migrations                               v2   schema change history + propose
    /migrations/[id]                        v2
    /migrations/new                         v2
  /dashboards                               v1   single pre-built ingestion health (v1)
                                            v2   custom dashboard builder
    /dashboards/[id]                        v2
    /dashboards/new                         v2
  /cost                                     v1   tenant cost overview
                                            v1   admin platform-wide cost (A)
    /cost/budgets                           v1   tenant budget config
    /cost/forecast                          v2
  /admin                                    (A only)
    /admin/fleet                            v1   cross-tenant connector health
    /admin/provisioning                     v1   per-tenant DIS state
    /admin/llm-ops                          v1   LLM operation audit, prompts, costs
    /admin/canonical-schema                 v1   write-side of canonical registry
    /admin/templates                        v2   marketplace curation
    /admin/composer                         v2   cluster utilization
    /admin/bigquery                         v2   slot reservations
  /onboarding                               v1   first-time wizard
  /docs                                     v1   in-app help
  /status                                   v1   DIS platform incidents
  /changelog                                v1
  /settings                                 v1   tenant LLM-assist opt-in (and other tenant prefs)
```

---

## Sidebar nav structure

Sidebar contents render based on active product (Ithina or DIS). DIS sidebar groups routes into the following sections, mirroring Ithina's pattern of "Overview / Governance / Access Control / Compliance":

```
DIS sidebar (Tenant view - Kowalski)
  OVERVIEW
    Dashboard                  /dis/dashboard
  INGESTION
    Sources                    /dis/sources
    Uploads                    /dis/uploads
    Templates                  /dis/templates
    Runs                       /dis/runs
    Backfills                  /dis/backfills
  QUALITY
    Validation                 /dis/validation
    Schema drift               /dis/validation/drift
    Freshness                  /dis/freshness
    Alerts                     /dis/alerts
  GOVERNANCE
    Canonical schema           /dis/canonical-schema
    Catalog                    /dis/catalog                (v2)
    Warehouse                  /dis/warehouse              (v2)
    Migrations                 /dis/migrations             (v2)
  INSIGHTS
    Dashboards                 /dis/dashboards
    Cost                       /dis/cost
  HELP
    Onboarding                 /dis/onboarding
    Docs                       /dis/docs
    Status                     /dis/status
    Changelog                  /dis/changelog
    Settings                   /dis/settings
```

```
DIS sidebar (Platform view - Anjali) adds an ADMIN section above HELP:
  ADMIN
    Fleet health               /dis/admin/fleet
    Provisioning               /dis/admin/provisioning
    LLM operations             /dis/admin/llm-ops
    Canonical schema (edit)    /dis/admin/canonical-schema
    Template marketplace       /dis/admin/templates       (v2)
    Composer                   /dis/admin/composer        (v2)
    BigQuery                   /dis/admin/bigquery        (v2)
```

Items hidden by Module Access permissions (DIS-specific role catalog, namespaced as `dis.*`) are not rendered. Anjali sees the full DIS sidebar regardless of any tenant's module config; gating applies to tenant users only.

---

## Page inventory by functional area

For each page: route, persona scope (T = tenant, A = admin, both = appears in both with persona-scoped data), v-phase, primary reads, primary writes. Read/write items here are the page-level summary; the full action inventory from the earlier list still applies.

### 1. Dashboard

`/dis/dashboard` - both - v1
Reads: ingest health summary, recent runs widget, active alerts widget, freshness scorecard, cost-this-period widget. Anjali's view aggregates across tenants; Kowalski's is single-tenant. Empty-state when tenant has no sources yet links to `/dis/onboarding`.
Writes: none. Widgets link to detail pages.

### 2. Sources

`/dis/sources` - both - v1
Reads: source list filtered by type / status / health badge. Anjali sees all tenants' sources with tenant column; Kowalski sees own tenant's only.
Writes (T): bulk pause / resume, delete (multi-select).

`/dis/sources/new` - T - v1
Wizard step order: type selection → assign to org node (single-node picker, reuses Ithina's org-tree component) → connection config (per-type form for the 9 source types) → test connection → schedule + review + save. Org-node assignment precedes config so the simpler tenant decision ("where in my org does this belong?") is made fresh, before the credential-heavy config work. Phase 5c.2b1 ships the 3 outer steps (type → org-node → schedule + save); 5c.2b2 inserts the config + test steps between org-node and schedule.
Writes (T): create source.

Org-node scoping uses a single `org_node_id` reference per source in v1. Multi-node attachment (one source serving multiple regions / stores) deferred to v2 if real demand surfaces; backend can later add a join table without breaking the v1 single-node API.

`/dis/sources/[id]` - both - v1
Reads: full config, credentials status, schedule, last 30-day volume trend, schema fingerprint, recent runs, validation results, freshness, owner, audit-log slice for this source.
Writes (T): pause / resume, run-now, rotate credentials, delete.
Writes (A): force-pause (incident response), reassign ownership.

`/dis/sources/[id]/edit` - T - v1
Writes: edit name, schedule, credentials, owner, org-node assignment.

`/dis/sources/[id]/runs` - both - v1
Reads: run history scoped to this source.

### 3. Runs

`/dis/runs` - both - v1
Reads: run history across all sources for tenant (or all tenants for Anjali). Filter by source / status / time range / triggered-by. Anjali sees tenant column.

`/dis/runs/[id]` - both - v1
Reads: timing, rows-in/out, log tail, error detail (if failed), DAG view of multi-step pipelines, downstream-effect (which tables touched), triggered-by.
Writes (T): retry, cancel, acknowledge failure (mute alert).
Writes (A): force-kill, bulk retry across tenants from `/dis/admin/fleet`.

`/dis/runs/active` - both - v1
Reads: live in-progress runs with ETA. Polling or SSE.

`/dis/runs/failed` - both - v1
Reads: failure queue sorted by recency, with quick-retry affordance.

### 4. Uploads (CSV one-off ingestion + LLM-assisted mapping)

`/dis/uploads` - both - v1
Reads: upload history (file name, template applied, rows ingested, status, who, when).
Writes (T): new upload (file picker + template picker or "create new template from this file").

`/dis/uploads/[id]` - both - v1
Reads: file metadata, template applied (or "ad-hoc"), LLM mapping confidence per column, columns the LLM couldn't confidently route, validation results, ingest outcome, sample of failing rows (PII-redacted by default), ingested-row count.
Writes (T): correct LLM mapping (per-column dropdown to canonical fields), mark column as ignore, confirm mapping (commits the upload), pin sample row as "good example" for future LLM passes, re-run with corrected mapping.
Writes (A): can review any tenant's upload for support, but write actions stay tenant-side.

PII handling: sample rows render with redaction by default. Redaction combines heuristic detection (regex/format match for emails, phone numbers, card-shape strings, SSN-shape strings) with canonical-schema PII tags. A "View raw" affordance is rendered for users carrying the `dis.pii.view` permission; each click writes an audit event capturing user, upload, column-set revealed, and reason (optional free-text). Default-redact applies even to admins; admins must hold `dis.pii.view` and audit-log to see raw.

LLM-assist gating: this page's LLM mapping confidence and proposal flow only renders when both layers of the LLM-assist hierarchy are on. Ithina Module Access defines whether LLM-assist is *available* to the tenant (compliance-level capability gate, controlled by Anjali). DIS tenant settings defines whether the tenant has *opted in* to LLM-assist (preference toggle, controlled by tenant). When either is off, the upload review falls back to the manual-mapping path: tenant maps each column to a canonical field via dropdown without LLM proposals. The manual-mapping path is a first-class fallback, not a degraded mode.

This page is the highest-value screen in v1 DIS. It is the human-in-the-loop moment that determines mapping quality and produces training signal. Design and build first.

### 5. Templates

`/dis/templates` - T - v1
Reads: tenant's template library, usage stats per template, last-success-rate, canonical schema version chip per template (highlighted when behind latest), pending-migration count.
Writes: create new (links to `/dis/templates/new`), duplicate, delete, bulk-migrate (when multiple templates share a pending migration).

Canonical schema inheritance is hybrid: additive canonical changes (new optional field, new synonym, new validator) auto-propagate into all templates without tenant action. Breaking canonical changes (field rename, type change, deprecation) leave templates pinned to the version they were created against, surface a migration prompt on tenant home and on this page, and require explicit tenant action to migrate. Templates display a version chip showing pinned version vs latest.

`/dis/templates/new` - T - v1
Wizard: upload sample CSV → LLM proposes name + mappings + validations + transformations + schedule heuristic → tenant reviews each proposal → save.

LLM proposal step is gated on the two-layer LLM-assist hierarchy (Ithina Module Access capability + DIS tenant opt-in). When either is off, the wizard skips proposal generation and presents the manual-mapping path: tenant names the template, maps each column to a canonical field via dropdown, defines validations and transformations explicitly. Same wizard, same outcome shape; just no LLM-proposed defaults.

`/dis/templates/[id]` - T - v1
Reads: schema mapping detail, transformation rules, validation rules, version history, last-N runs that used this template, LLM mapping accuracy trend, pinned canonical-schema version with diff against latest if behind.
Writes: edit (links to `/dis/templates/[id]/edit`), test against sample file (dry-run), pin sample row, set as default for a source, migrate to latest canonical version (when behind, with diff preview before commit).

`/dis/templates/[id]/edit` - T - v1
Writes: rename, edit mappings, edit transformations, edit validations, version-bump.

`/dis/templates/marketplace` - both - v2
Reads (T): platform-published templates filtered by tenant industry, other tenants' shared templates.
Writes (T): install, fork, share own (opt-in).
Writes (A): curate, approve tenant-shared, retire stale.

### 6. Canonical schema registry

`/dis/canonical-schema` - both - v1
Reads: domain / entity / field browser. Synonyms visible. Type constraints, format validators, allowed-value enums.
Writes (T): none (read-only for tenants).

`/dis/canonical-schema/[domain]` - both - v1
Reads: entities under a domain (Sales / Inventory / Customers / Suppliers / Stores / Products / etc.).

`/dis/canonical-schema/[domain]/[entity]` - both - v1
Reads: field list, descriptions, examples, synonyms, lineage (which tenant template columns map here across the fleet - A only).

`/dis/canonical-schema/coverage` - T - v1
Reads: tenant's templates vs. canonical coverage. Gaps highlighted ("you have no template covering Suppliers").

`/dis/admin/canonical-schema` - A - v1
Writes: create / edit / deprecate fields, add synonyms, version-bump, promote tenant-discovered fields, force re-mapping of historical uploads.

Version-bump flow forces an explicit "is this a breaking change?" decision per change (rename, type change, deprecation are breaking by default; new optional field, new synonym, new validator are additive by default - admin can override classification). Decision is audit-logged and drives the inheritance behavior on tenant templates: additive auto-propagates, breaking pins existing templates and surfaces tenant migration prompts. Diff preview before commit shows affected tenant template count and field-level impact across the fleet.

The canonical schema must exist before tenants onboard. Sanjeev has built schemas already, so v1 work is exposing them via UI, not designing them.

### 7. Validation & quality

`/dis/validation` - both - v1
Reads: validation rule registry per source/table, rule results timeline, top failing rules last 7/30 days, data quality composite score per source/table.
Writes (T): create / edit / delete rule, set null tolerance, enable/disable schema-drift auto-block.

`/dis/validation/rules/[id]` - both - v1
Reads: rule definition, recent pass/fail history, sample failing rows (PII-redacted by default; `dis.pii.view` permission gates raw view, audit-logged per click - same policy as `/dis/uploads/[id]`).
Writes (T): edit, disable, delete.

`/dis/validation/drift` - both - v1
Reads: schema-drift event inbox (added / removed / type-changed columns) with diff view. LLM-proposed interpretation per event ("looks like a rename of X") rendered when LLM-assist is on for the tenant; otherwise diff is shown without LLM interpretation and the operator decides manually.
Writes (T): accept (auto-evolve schema), reject (block ingestion until manual fix), mark as rename.

`/dis/validation/drift/[id]` - both - v1
Reads: full diff, affected templates, downstream impact analysis.

### 8. Freshness & SLA

`/dis/freshness` - both - v1
Reads: per-source freshness widget, SLA compliance % over time, breach incidents.
Writes (T): define SLA per source, configure breach alert recipients.

`/dis/freshness/breaches` - both - v1
Reads: breach history with duration, recovery, root cause if known.

### 9. Alerts

`/dis/alerts` - both - v1
Reads: alert inbox (open / acknowledged / resolved), severity, source, suggested remediation. Anjali sees fleet inbox; Kowalski sees own.
Writes (T): acknowledge, resolve, snooze.

`/dis/alerts/[id]` - both - v1
Reads: triggering condition, history of similar alerts, remediation suggestions.
Writes (T): acknowledge, resolve, snooze.

`/dis/alerts/rules` - both - v1
Reads: alert rule registry (condition + threshold + channel + severity).
Writes (T): create / edit / delete rule.

`/dis/alerts/rules/[id]` - both - v1
Writes (T): edit.

`/dis/alerts/channels` - T - v1
Reads: configured channels (email, Slack, PagerDuty, webhook).
Writes: add / edit / test / delete channel, configure routing.

### 10. Backfills

`/dis/backfills` - both - v1
Reads: backfill job history per tenant, in-progress with progress bar, cost estimate.
Writes (T): create backfill (source + date range + dry-run option), cancel, schedule for off-peak.

`/dis/backfills/[id]` - both - v1
Reads: job detail, progress, cost-actual.

### 11. Catalog (Dataplex passthrough)

`/dis/catalog` - both - v2
Reads: searchable catalog of tables, columns, business glossary, tags.

`/dis/catalog/[table]` - both - v2
Reads: column-level docs, owner, sample values (permission-gated), sensitivity classification, PII flags.
Writes (T): edit description, assign owner, apply tags, mark PII.

`/dis/catalog/lineage` - both - v2
Reads: lineage graph source → raw → staging → curated → consumer.

`/dis/catalog/coverage` - both - v2
Reads: % tables documented, % columns described, % tagged. The "100% catalog coverage" KPI surface from your spec.

### 12. Warehouse zones

`/dis/warehouse` - both - v2
Reads: zone overview (raw / staging / curated) with size, table count, last-updated.

`/dis/warehouse/[zone]` - both - v2
Reads: dataset list per zone.

`/dis/warehouse/[zone]/[dataset]` - both - v2
Reads: tables in dataset.

`/dis/warehouse/[zone]/[dataset]/[table]` - both - v2
Reads: schema, partition strategy, cluster keys, sample rows (gated), refresh SLA, lineage, owner, storage cost.
Writes (T): trigger refresh, archive, re-cluster / re-partition (advanced).

`/dis/warehouse/promotions` - both - v2
Reads: staging-to-curated promotion queue, why-not-promoted reasons.
Writes (T): promote (manual approval flow if guardrail set).
Writes (A): force-promote, define zone-promotion policies.

### 13. Schema migrations

`/dis/migrations` - both - v2
Reads: migration history (when, what changed, who, rollback available).

`/dis/migrations/[id]` - both - v2
Reads: full diff, compatibility check results, downstream impact.
Writes (T): execute (with approval gate if guardrail), rollback.

`/dis/migrations/new` - T - v2
Writes: propose change (add / drop / rename column, change type), dry-run, submit for approval.

### 14. Dashboards (BI-style)

`/dis/dashboards` - both - v1
Reads (v1): single pre-built "Ingestion Health" dashboard. Anjali sees fleet variant; Kowalski sees tenant-scoped variant.
Reads (v2): list of custom dashboards (tenant-built).

`/dis/dashboards/[id]` - both - v2
Reads: custom dashboard view.
Writes (T): edit, share within tenant (view-only links), schedule digest, export CSV/PDF, pin to tenant home.

`/dis/dashboards/new` - T - v2
Writes: create dashboard from BQ saved query → chart picker → save.

### 15. Cost & resource usage

`/dis/cost` - both - v1
Reads (T): BQ query cost per period, storage cost per zone, Composer DAG-run cost, cost trend, cost-per-source attribution, anomaly callouts, LLM token allowance + consumption + projected overage (when LLM-assist is on).
Reads (A): platform-wide cost dashboard, per-tenant attribution, expensive-tenant flagging, fleet-wide LLM token consumption.

LLM cost model is bundled allowance + overage. Each tenant tier carries a monthly token allowance; usage past allowance bills as overage. v1 ships the UI but defaults all tenants to unlimited allowance until commercial terms finalize - tenants see a "consumption this month" widget without overage projections until allowances are turned on. Soft-block alert when tenant crosses 90% of allowance (when set); no hard-block in v1.

`/dis/cost/budgets` - T - v1
Writes: set tenant cost budget, alert thresholds (BQ + storage + Composer + LLM tokens, separate budgets per category).

`/dis/cost/forecast` - both - v2
Reads: 30/90-day cost projection.

### 16. Admin-only views

`/dis/admin/fleet` - A - v1
Reads: cross-tenant connector health matrix, top failing pipelines platform-wide, % tenants meeting SLA, drill-into-any-tenant capability.
Writes: bulk retry, bulk pause across tenants (incident response).

`/dis/admin/provisioning` - A - v1
Reads: per-tenant DIS provisioning state (BQ dataset created, IAM bindings, sample pipeline seeded, canonical schema visibility verified).
Writes: provision DIS for newly-onboarded tenant (manual until Phase 4c mutations land), decommission DIS, force re-sync catalog metadata.

`/dis/admin/llm-ops` - A - v1
Reads: LLM operation audit (every prompt / response / tenant action), prompt registry with version history, confidence threshold config, token usage / cost trend per tenant and fleet-wide, per-tenant LLM-assist enablement (capability + opt-in state, both layers visible), per-tenant token allowance and overage state.
Writes: edit prompts (versioned, A/B-testable), set confidence thresholds, set per-tenant token allowance (default unlimited in v1), toggle the capability layer of the LLM-assist hierarchy per tenant (the opt-in layer stays tenant-controlled and is read-only here), force-disable LLM-assist per tenant in incident scenarios (overrides tenant opt-in temporarily, audit-logged).

`/dis/admin/templates` - A - v2
Writes: marketplace curation, approve tenant-shared templates, retire stale.

`/dis/admin/composer` - A - v2
Reads: Composer cluster utilization, DAG queue depth, worker health.

`/dis/admin/bigquery` - A - v2
Reads: BQ slot reservation status, query backlog, top consumers.

### 17. Onboarding

`/dis/onboarding` - T - v1
Wizard: first-time DIS user. Pick connector type → connect → upload sample → LLM proposes everything → tenant approves → first ingest runs → see first data. Becomes the time-to-first-data metric. The most leverage-positive UX in v1.

### 18. Help / status / changelog

`/dis/docs` - both - v1
Reads: in-app docs for connector setup, glossary, troubleshooting.

`/dis/status` - both - v1
Reads: DIS platform incident status, planned maintenance.

`/dis/changelog` - both - v1
Reads: what shipped recently.

---

## Cross-product surfaces (live in Ithina, referenced from DIS)

These surfaces are not new DIS pages. They already exist (or are scoped to exist) in Ithina's `/superadmin/...` namespace and DIS feeds into / reads from them. Worth listing so the build plan handles cross-product wiring correctly.

`Audit log` - Ithina's `/superadmin/audit-log` (currently MSW-only). DIS publishes events here: connector changes, schema migrations, manual runs, credential rotations, permission grants, data exports, deletion events. DIS does not host its own audit viewer; it links into Ithina's filtered-by-source view.

`Roles & Permissions` - Ithina's `/superadmin/roles` (currently MSW-only). DIS-specific roles (`dis.viewer`, `dis.editor`, `dis.admin`) and permissions (`dis.source.configure`, `dis.template.edit`, `dis.canonical-schema.edit`, `dis.pii.view`, `dis.cost.budgets.edit`, etc.) are registered in Ithina's catalog. DIS reads effective permissions but does not write here. The `dis.pii.view` permission gates the "View raw" affordance on sample-row displays in upload review and validation rules; each click writes an audit event capturing user, scope, and reason.

`Module Access` - Ithina's `/superadmin/modules` (currently MSW-only). Multiple toggles per tenant: the top-level "DIS" toggle determines whether DIS appears in the product-switcher, and a sub-toggle "DIS LLM-assist" defines the *capability* layer of the LLM-assist hierarchy (whether the tenant is *allowed* to use LLM-assist; tenant opt-in is the second layer, lives in DIS tenant settings). DIS reads both at session start. Anjali controls Module Access; tenant cannot self-modify.

`Guardrails` - Ithina's `/superadmin/guardrails` (currently MSW-only). DIS data-quality policies (max null %, schema-drift tolerance, freshness SLA per source, mandatory-documentation, migration-approval gate) live here and apply to DIS operations.

`Tenants list / detail` - Ithina's `/superadmin/tenants` (wired). DIS admin views may deep-link into a specific tenant for cross-product context.

`Org tree` - Ithina's `/superadmin/org` (wired). DIS uses org nodes to scope sources (per-region pipeline, per-store feed). The picker component should be reused, not rebuilt.

`Notifications` - Ithina's `/superadmin/notifications` (currently MSW-only). DIS-routed notifications surface here.

---

## Ithina dependencies blocking DIS frontend

DIS frontend can ship a substantial v1 against MSW for missing Ithina surfaces, but the following must be real-backend before DIS goes to production:

1. **Module Access wiring.** Determines whether DIS appears in the product switcher. Without it, every tenant sees DIS regardless of license.
2. **Roles & Permissions wiring with module-namespaced catalog.** DIS-scoped permissions must register in Ithina's catalog and be assignable. Without it, DIS sub-features cannot be permission-gated.
3. **Audit log reads.** DIS events publish to Ithina's audit trunk. Without the reader, events are written but not viewable.

The following are valuable but not blocking:

- Dashboard composites (Ithina's own dashboard, not DIS dashboards).
- Notifications routing (DIS alerts can route directly via DIS backend until Ithina's channel routing exists).
- Guardrails (DIS can enforce its own policies internally until Ithina's guardrail engine takes over).

Phase 4c mutations are NOT blocking for DIS frontend v1 reads. They are blocking for DIS provisioning (admin manually provisions until 4c) and for tenant self-service flows. Tenants can still operate DIS once provisioned.

---

## Persona expectations

**Kowalski (Tenant user, Żabka)**

Lands on Ithina. If Module Access has DIS enabled for Żabka, Ithina header shows the product switcher with both options. Switches to DIS, lands on `/dis/dashboard`. Sees ingestion health for Żabka only, all sources scoped to his tenant via JWT/RLS at the DIS backend. Configures sources, uploads CSVs, reviews LLM mappings, manages alerts, monitors freshness. Cannot access `/dis/admin/*` routes (404 or permission-denied). Cannot see other tenants in any list.

**Anjali (Platform user)**

Lands on Ithina. Product switcher shows all enabled products. Switches to DIS, lands on `/dis/dashboard` showing fleet aggregate. Has the additional ADMIN sidebar section. Can drill into any tenant's DIS state for support. Can pause / retry / kill operations across tenants. Edits canonical schema. Manages LLM prompts and confidence thresholds. Provisions DIS for new tenants (manual until 4c).

**Future tenant-admin role (out of scope for v1)**

A tenant-admin persona between Anjali and Kowalski - full DIS control within their tenant, including template marketplace publishing, custom dashboards, advanced cost controls. Not built in v1; tenant users get a single role for now.

---

## Known-deferred (v1 will ship without these)

- Per-page deep-link via URL state for drill-down (similar to org-tree's lost shareable-node-link in Phase 4e). Lazy-loaded UI elements like template marketplace, run-detail tabs, dashboard widgets will not be deep-linkable in v1. Restorable later if UX feedback demands.
- Tenant-tenant template sharing (v2 marketplace).
- Advanced lineage visualization (v2).
- Real-time streaming ingestion UI (out of scope entirely - your spec is batch-only).
- Direct BigQuery SQL editor (Google Cloud Console covers this).
- Visual ETL pipeline builder (Composer DAGs are code; a different product).
- Mobile-optimized layouts (admin tooling, desktop-first).
- Multi-node attachment for sources. v1 is single `org_node_id` per source; multi-node (one feed serving multiple regions / stores) deferred to v2 if real demand surfaces. Backend can later add a join table without breaking the v1 single-node API.
- LLM cost hard-block at allowance exhaustion. v1 ships soft-block (warning at 90%) only; hard-block deferred to v2 once real allowances are turned on and overage billing is operational.

---

## Resolved decisions

These were parked questions in earlier drafts; resolved before build plan scoping. Calls captured for traceability.

1. **LLM-assist toggle: hierarchical (Module Access capability + DIS opt-in).** Ithina Module Access defines whether the tenant is *allowed* to use LLM-assist (compliance-level capability gate, Anjali-controlled). DIS tenant settings defines whether the tenant *opts in* to LLM-assist (preference toggle, tenant-controlled). Both must be on for LLM proposals to render; either off falls back to manual-mapping path. Reasoning: regulated-tenant compliance and tenant preference are different policies sharing an off-switch; modeling separately keeps governance audit trail clean.

2. **PII redaction: heuristic + canonical-schema-tag mask by default; `dis.pii.view` permission gates raw view, audit-logged per click.** Sample-row displays on upload review and validation rules pages mask emails / phone-shape / card-shape / SSN-shape strings via regex regardless of canonical-schema tagging, then add canonical-schema PII tags on top. "View raw" affordance for users carrying `dis.pii.view`; each click writes audit event. Default-redact applies to admins too. Reasoning: defense in depth (heuristic catches common PII even on untagged columns), accountability (privileged action, audit-logged), debuggable (operators with permission can still see the data).

3. **LLM cost attribution: bundled allowance + overage billing, allowance config built in v1, default unlimited.** Each tenant tier carries a monthly token allowance; overage billed per token. v1 ships UI supporting the model but defaults all tenants to unlimited until commercial terms finalize. Soft-block alert at 90% of allowance (when set); no hard-block in v1. Reasoning: matches mature SaaS pricing patterns, gives platform a knob to tune without contract renegotiation, avoids retroactive UI rework when allowances turn on.

4. **Canonical schema inheritance: hybrid by change type.** Additive changes (new optional field, new synonym, new validator) auto-propagate into all tenant templates. Breaking changes (field rename, type change, deprecation) leave templates pinned to their creation-version, surface migration prompts on tenant home and templates list, require explicit tenant action to migrate. Admin classifies each change at version-bump time (defaults: rename / type change / deprecation = breaking; new optional / new synonym / new validator = additive); audit-logged. Reasoning: treats schema like every mature schema-evolution system (Avro / Protobuf / GraphQL); prevents silent breakage while avoiding stale-template graveyards.

5. **Org-node scoping for sources: single `org_node_id` in v1, multi-attach deferred to v2.** Source create/edit wizard uses single org-node picker reusing Ithina's org-tree component. Source detail shows one breadcrumb. Source list filterable by node with "include descendants" toggle. Reasoning: 80% of cases fit single-node model; backend can add join table later without breaking v1 API; multi-attach builds gated on real tenant demand.

6. **5c.1c-resolution: Settings added to HELP sidebar section after smoke surfaced discoverability problem with contextual-link-only approach.** The 5c.1c plan kept `/dis/settings` reachable via direct URL plus a contextual `Manage in DIS settings` link from `MappingReviewView`'s LLM-off header — no sidebar entry, to preserve the 17/21 sidebar count locked in 5b.1. Smoke revealed any user not currently on a PENDING_REVIEW upload's LLM-off header had no path to settings. Fix: append `Settings` to the existing HELP section (where tenant-side housekeeping items already live: Onboarding / Docs / Status / Changelog). Sidebar count moves to 18/22. Adding a dedicated SETTINGS section for one item would have been over-structuring.

---

## Build readiness

Surface map is reference-level complete for v1. Sufficient input to:

- Sketch wireframes / page-level designs.
- Scope chunked frontend build.
- Identify shared components to extract (org-node picker, source health badge, run status chip, etc.).
- Identify Ithina surfaces that need real-backend before DIS production cutover.

Build plan to follow as a separate doc.
