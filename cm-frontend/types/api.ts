// Backend-served types are re-exported from `openapi-generated.ts`, which
// is regenerated from `docs/openapi.json` via `pnpm gen:types`. Re-run after
// any backend contract change; tsc will surface every divergence.
//
// Hand-maintained types remain only for frontend-only concerns (UI state,
// component props, types whose backend equivalent doesn't exist in v0).
// Each hand-maintained block carries a comment about its origin.

import type { components } from "./openapi-generated";

type Schemas = components["schemas"];

// ----------------------------------------------------------------------------
// Backend-served — re-exported from generated.
// ----------------------------------------------------------------------------

// Tenants
export type Tenant = Schemas["TenantsListItem"];
export type TenantDetail = Schemas["TenantDetail"];
export type TenantStats = Schemas["TenantsStatsResponse"];
export type TenantStatus = Schemas["TenantStatus"];
export type TenantTier = Schemas["TenantTier"];
export type TenantRegion = Schemas["TenantRegion"];
export type TenantIndustry = Schemas["TenantIndustry"];

// Users (Phase 4d wired against backend's split resources; the
// frontend's hybrid `User` type was deleted along with this wiring).
// Backend doesn't carry `mfa_enabled`, `roles[]`, `location_count`,
// `last_active_at` in v0 — those columns/sections were dropped from
// the UI; they return when Sanjeev extends the schema.
export type PlatformUser = Schemas["PlatformUserRead"];
export type TenantUser = Schemas["TenantUserRead"];
export type PlatformUserStatus = Schemas["PlatformUserStatus"];
export type TenantUserStatus = Schemas["TenantUserStatus"];
export type PlatformUserListResponse = Schemas["PlatformUserListResponse"];
export type TenantUserListResponse = Schemas["TenantUserListResponse"];

// Modules + lookups + pagination envelope
export type Module = Schemas["Module"];
export type LookupItem = Schemas["LookupItem"];
export type Pagination = Schemas["Pagination"];

// Stores (Phase 5-stores wired against Steps 6.17.x).
export type Store = Schemas["StoreListItem"];
export type StoreDetail = Schemas["StoreDetail"];
export type StoreListResponse = Schemas["StoreListResponse"];
export type StoreStatus = Schemas["StoreStatus"];
export type TaxTreatment = Schemas["TaxTreatment"];

// Org tree (Phase 4e wired). Backend's OrgNodeTreeItem is RECURSIVE
// — `children: OrgNodeTreeItem[]` is built server-side from ltree
// paths; the frontend doesn't reassemble. `name` (not `display_name`)
// is the display string. `loaded_children` enum drives lazy fetches
// from the children endpoint:
//   "all"     — every child present
//   "partial" — some present, more via /children?offset>0
//   "none"    — true leaf (has_children=false) OR depth-cut node
//               (has_children=true; call /children to load)
export type OrgTreeResponse = Schemas["OrgTreeResponse"];
export type OrgTreeStats = Schemas["OrgTreeStats"];
export type OrgNodeTreeItem = Schemas["OrgNodeTreeItem"];
export type OrgNodeChildrenResponse = Schemas["OrgNodeChildrenResponse"];
export type OrgNodeStatus = Schemas["OrgNodeStatus"];
export type OrgNodeType = Schemas["OrgNodeType"];

// ----------------------------------------------------------------------------
// Hand-maintained — frontend-only or no backend equivalent in v0.
// ----------------------------------------------------------------------------
//
// Disposition summary (Phase 5f.V audit, 2026-05-15):
//
//   ModuleCode (DIS addition)        KEEP — awaits backend adding DIS to
//                                           module_code_enum (Sanjeev queue)
//   ModuleCard / MatrixCell / ...    KEEP — Omit<>&{} bridge to ModuleCode;
//                                           simplifies when DIS lands backend
//   Lookups (discrete-keyed shape)   KEEP — frontend ergonomics; backend
//                                           ships free-form Record<string, ...>
//   AuditResult / AuditEvent / ...   KEEP — no backend equivalent (Step 6.2)
//   UnavailableReason                KEEP — compile-time safety over
//                                           backend's free-form string
//   RecentActivityRow                KEEP — depends on Step 6.2 audit-logs
//   Notification                     KEEP — no backend equivalent
//
// Every surface carries a comment naming what it awaits. Retirements
// follow Sanjeev shipment; the surfaces above are intentional debt, not
// orphans.

// ModuleCode: backend's `Module.code` is a free-form `string`. The frontend
// keeps this enum for compile-time safety in module-summary UI.
//
// AWAITED DEBT (Phase 5d.1): "DIS" is a frontend-only addition. Awaits
// backend adding DIS to the module_code_enum so the launcher's DIS tile
// gates via the same matrix mechanism as product modules. MSW handlers
// seed it ENABLED for tenants holding any product module (Buc-ee's +
// Żabka Group). Retire this union override when backend ships DIS in
// ModuleCode; generated type then becomes canonical.
//
// (Phase 5f.V audit: ROOS retirement awaited-debt paragraph removed.
// Backend retired ROOS from the openapi spec at commit 9462e11 and the
// regenerated openapi-generated.ts at d1d1dd7 reflects it. The only
// remaining justification for hand-maintaining this union is the DIS
// addition above.)
export type ModuleCode =
  | "GOAL_CONSOLE"
  | "PRICING_OS"
  | "PERISHABLES_ASSISTANT"
  | "PROMOTIONS_ASSISTANT"
  | "ADMIN"
  | "DIS";


// Lookups: backend's response is `{ lookups: Record<string, LookupItem[]> }`.
// The frontend keeps a discrete-keyed convenience shape so consumers can
// access `lookups.tenant_tiers` without indexing by string. The wrapping
// `{ lookups: ... }` envelope will land when this surface gets wired.
export type Lookups = {
  tenant_tiers: LookupItem[];
  tenant_industries: LookupItem[];
  tenant_regions: LookupItem[];
  tenant_statuses: LookupItem[];
  user_statuses: LookupItem[];
  modules: LookupItem[];
  org_node_types: LookupItem[];
  permission_actions: LookupItem[];
  permission_scopes: LookupItem[];
  role_codes: LookupItem[];
};

// Roles + permissions (Phase 5e.2 wired against Sanjeev's RBAC catalog
// endpoints; the hand-maintained pre-5e Role/Permission shapes were
// deleted along with this wiring). Audience visibility is enforced at
// the backend's app layer (roles + role_permissions tables are
// platform-global, no RLS); permissions table is open reference data.
//
// D-30 exceptions in this surface family:
//   /roles                 — pre-grouped {platform_roles, tenant_roles}
//   /roles/{id}/permissions — parent-echo {role_id, role_name, items}
//   /permission-matrix     — render-ready {roles, rows} (position-
//                             aligned cells[i] under roles[i])
// /permissions follows D-30 normally with {items, pagination}.
export type RoleAudience = Schemas["RoleAudience"];
export type RoleStatus = Schemas["RoleStatus"];
export type RoleListItem = Schemas["RoleListItem"];
export type AudienceBlock = Schemas["AudienceBlock"];
export type RoleListResponse = Schemas["RoleListResponse"];

export type PermissionAction = Schemas["PermissionAction"];
export type PermissionScope = Schemas["PermissionScope"];
export type PermissionResource = Schemas["PermissionResource"];
export type PermissionRead = Schemas["PermissionRead"];
export type PermissionListResponse = Schemas["PermissionListResponse"];
export type RolePermissionsResponse = Schemas["RolePermissionsResponse"];
export type PermissionMatrixResponse = Schemas["PermissionMatrixResponse"];
export type PermissionMatrixRow = Schemas["PermissionMatrixRow"];
export type PermissionMatrixRoleColumn = Schemas["PermissionMatrixRoleColumn"];

// Phase 5d.3: role-assignments endpoint (Sanjeev's Step 6.8.3).
// Org-node-level scoping: tenant assignments carry an org_node
// reference so the same user can hold OWNER at the tenant root and
// STORE_MANAGER at a specific store. UI surfaces org_node as a
// column or assignments read as duplicate/contradictory.
export type RoleAssignmentsResponse = Schemas["RoleAssignmentsResponse"];
export type PlatformAssignmentsBlock = Schemas["PlatformAssignmentsBlock"];
export type TenantAssignmentsBlock = Schemas["TenantAssignmentsBlock"];
export type PlatformAssignmentItem = Schemas["PlatformAssignmentItem"];
export type TenantAssignmentItem = Schemas["TenantAssignmentItem"];
export type UserRoleAssignmentStatus = Schemas["UserRoleAssignmentStatus"];

// Audit (no backend equivalent in v0)
export type AuditResult = "SUCCESS" | "DENIED" | "PENDING";

export type AuditEvent = {
  id: string;
  occurred_at: string;
  actor_user_id: string | null;
  actor_name: string;
  actor_role: string | null;
  tenant_id: string | null;
  tenant_name: string | null;
  action: string;
  resource: string;
  scope: PermissionScope | null;
  result: AuditResult;
  ip: string | null;
};

export type AuditDetail = AuditEvent & {
  payload: Record<string, unknown>;
  related_event_ids: string[];
};

// Module Access (Phase 5e.3 wired against Sanjeev's two endpoints
// — /module-access/modules + /module-access/matrix). Backend ships
// server-resolved tier_label / status_label / module_label per the
// new Step 6.7 label-handling convention; frontend consumes those
// directly rather than client-side useLookups for these fields.
//
// D-30 exceptions:
//   /module-access/modules — fixed-cardinality {items: 6}
//   /module-access/matrix  — paginated {items, pagination} with
//                             position-aligned cells[i] under
//                             modules.items[i]
//
// The pre-5e3 ModuleSummary + TenantModuleRow hand types were
// deleted; backend's tagline field has no equivalent (UI dropped it
// per integration plan).
//
// Phase 5e.0: `module_code` is narrowed to the hand-maintained
// ModuleCode union (which retired ROOS + adds DIS). openapi.json
// is stale on both points until backend re-exports — until then,
// the hand union is the canonical surface for consumers.
export type ModuleCard = Omit<Schemas["ModuleCard"], "module_code"> & {
  module_code: ModuleCode;
};
export type ModulesResponse = Omit<Schemas["ModulesResponse"], "items"> & {
  items: ModuleCard[];
};
export type MatrixCell = Omit<Schemas["MatrixCell"], "module_code"> & {
  module_code: ModuleCode;
};
export type MatrixRow = Omit<Schemas["MatrixRow"], "cells"> & {
  cells: MatrixCell[];
};
export type MatrixResponse = Omit<Schemas["MatrixResponse"], "items"> & {
  items: MatrixRow[];
};


// Dashboard stats (Phase 5e.4 wired against Sanjeev's two endpoints
// — /dashboard/fleet-stats + /dashboard/governance-stats). Card-
// shaped responses (deliberate D-30 exception — UI bundle, not a
// paginatable collection). The pre-5e4 hand-maintained DashboardKPIs
// flat shape was deleted along with this wiring.
//
// `available: false` cards carry an `unavailable_reason` from the v0
// vocabulary. Frontend renders these with a "Coming soon" treatment;
// MUST NOT read `value` as meaningful when `available: false`. Type-
// stable sentinels appear in `value` for shape stability when the
// stub flips to real (D-31 append-only).
export type DeltaBlock = Schemas["DeltaBlock"];
export type FleetStatsResponse = Schemas["FleetStatsResponse"];
export type ActiveTenantsCard = Schemas["ActiveTenantsCard"];
export type PlatformUsersCard = Schemas["PlatformUsersCard"];
export type StoresCard = Schemas["StoresCard"];
export type MrrAggregatedCard = Schemas["MrrAggregatedCard"];
export type GovernanceStatsResponse = Schemas["GovernanceStatsResponse"];
export type PendingApprovalsCard = Schemas["PendingApprovalsCard"];
export type GuardrailsFired24hCard = Schemas["GuardrailsFired24hCard"];
export type CustomRolesCard = Schemas["CustomRolesCard"];
export type ModulesDeployedCard = Schemas["ModulesDeployedCard"];

// Hand-maintained: backend's `unavailable_reason` is a free-form
// string in the schema, but the v0 vocabulary is fixed at 3 values.
// Frontend keeps the union for compile-time safety in the friendly-
// text mapping; falls back to raw enum on unknown values.
export type UnavailableReason =
  | "approvals_table_not_built"
  | "audit_logs_or_guardrails_not_wired"
  | "custom_role_creation_not_shipped";

// Phase 5c.partial-deploy.hotfix2: TopTenantRow removed. The Top
// Tenants panel now calls tenantsApi.list({sort:
// "num_users_active_desc", limit: 10}) and consumes Tenant
// directly. TenantsListItem is a strict superset of the prior
// TopTenantRow shape (id / name / industry / country / tier /
// num_users_active / num_stores all present).

export type RecentActivityRow = {
  id: string;
  occurred_at: string;
  actor_name: string;
  action_summary: string;
  result: AuditResult;
};

// Client onboarding wizard (Slice 4, wired against backend Slices 1-3:
// section endpoints, onboarding-state, documents with signed URLs).
// All re-exported from generated; regenerate with `pnpm gen:types` after
// any backend contract change.
export type TenantCreateRequest = Schemas["TenantCreateRequest"];
export type TenantPatchRequest = Schemas["TenantPatchRequest"];

export type LegalProfileRead = Schemas["LegalProfileRead"];
export type LegalProfileUpsertRequest = Schemas["LegalProfileUpsertRequest"];
export type TaxRegistrationItem = Schemas["TaxRegistrationItem"];
export type TaxRegistrationInput = Schemas["TaxRegistrationInput"];
export type TaxRegistrationsRead = Schemas["TaxRegistrationsRead"];
export type TaxRegistrationsReplaceRequest =
  Schemas["TaxRegistrationsReplaceRequest"];
export type BillingProfileRead = Schemas["BillingProfileRead"];
export type BillingProfileUpsertRequest =
  Schemas["BillingProfileUpsertRequest"];
export type ContactItem = Schemas["ContactItem"];
export type ContactInput = Schemas["ContactInput"];
export type ContactsRead = Schemas["ContactsRead"];
export type ContactsReplaceRequest = Schemas["ContactsReplaceRequest"];

export type OnboardingStateResponse = Schemas["OnboardingStateResponse"];
export type OnboardingSectionsPresent = Schemas["OnboardingSectionsPresent"];
export type OnboardingDocumentsBlock = Schemas["OnboardingDocumentsBlock"];
export type OnboardingProvisioning = Schemas["OnboardingProvisioning"];
export type OnboardingPatchRequest = Schemas["OnboardingPatchRequest"];

export type DocumentRead = Schemas["DocumentRead"];
export type DocumentUploadUrlRequest = Schemas["DocumentUploadUrlRequest"];
export type DocumentUploadUrlResponse = Schemas["DocumentUploadUrlResponse"];
export type DocumentsListResponse = Schemas["DocumentsListResponse"];
export type DocumentDownloadUrlResponse =
  Schemas["DocumentDownloadUrlResponse"];
export type DocumentRejectRequest = Schemas["DocumentRejectRequest"];

// Auth0 provisioning results (Slice 5, Access & users). First frontend
// wiring of the provision-auth0 endpoints. Both are Auth0-side reports;
// the tenant org id is now also persisted server-side (option a) so
// onboarding-state.auth0_organization is a durable TRUE/FALSE.
export type TenantOrgProvisionResult = Schemas["TenantOrgProvisionResult"];
export type TenantUserProvisionResult = Schemas["TenantUserProvisionResult"];

// Notifications (no backend equivalent in v0)
export type Notification = {
  id: string;
  title: string;
  body: string;
  occurred_at: string;
  read: boolean;
  deep_link: string;
};
