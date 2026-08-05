import {
  Activity,
  Boxes,
  Building2,
  FileText,
  LayoutDashboard,
  Map,
  Network,
  Shield,
  Store,
  Users,
} from "lucide-react";

import type { NavGroup } from "@/components/chrome/Sidebar";

// Ithina Superadmin Console nav structure. Phase 5g.1 added the
// optional `requires` field on each NavItem; the Sidebar component
// filters items via `hasPermission` against the cached grant list
// (lib/auth/permissions-check.ts). Items without `requires` are
// always visible to authenticated users (currently: Dashboard only).
//
// Tuples sourced from the live /me/permissions grant set probed
// during 5g.1 pre-flight: PLATFORM holds VIEW.GLOBAL on most ADMIN
// resources; TENANT-OWNER holds VIEW.TENANT only. Sidebar items that
// scope to GLOBAL (e.g. cross-tenant Tenants list, Module Access
// toggle) naturally hide for TENANT-OWNER.
export const ithinaSidebarNavItems: NavGroup[] = [
  {
    heading: "Overview",
    items: [
      {
        href: "/superadmin/dashboard",
        label: "Platform Dashboard",
        labelTenant: "Dashboard",
        icon: LayoutDashboard,
      },
    ],
  },
  {
    heading: "Governance",
    items: [
      {
        href: "/superadmin/tenants",
        label: "Tenants",
        icon: Building2,
        requires: { module: "ADMIN", resource: "TENANTS", action: "VIEW", scope: "GLOBAL" },
      },
      {
        href: "/superadmin/stores",
        label: "Stores",
        icon: Store,
        requires: { module: "ADMIN", resource: "STORES", action: "VIEW" },
      },
      {
        href: "/superadmin/org",
        label: "Organization Tree",
        icon: Network,
        requires: { module: "ADMIN", resource: "ORG_NODES", action: "VIEW" },
      },
      {
        href: "/superadmin/users",
        label: "Users",
        icon: Users,
        requires: { module: "ADMIN", resource: "USERS", action: "VIEW" },
      },
    ],
  },
  {
    heading: "Access Control",
    items: [
      {
        href: "/superadmin/roles",
        label: "Roles & Permissions",
        icon: Shield,
        requires: { module: "ADMIN", resource: "ROLES", action: "VIEW" },
      },
      {
        // Module Access toggle gates on ADMIN.TENANTS.OVERRIDE.GLOBAL
        // (Step 6.15 aliased tuple per BUILD_PLAN Finding @ Phase 5j).
        // TENANT-OWNER lacks OVERRIDE.GLOBAL so this hides naturally.
        // Sanjeev queue: tuple split or RBAC explicit exclusion when
        // Phase 5g grants TENANT users any OVERRIDE.GLOBAL surface.
        href: "/superadmin/modules",
        label: "Module Access",
        icon: Boxes,
        requires: { module: "ADMIN", resource: "TENANTS", action: "OVERRIDE", scope: "GLOBAL" },
      },
    ],
  },
  {
    // MODULES — added in Synapse slice 8a. Placed between Access Control and
    // Compliance because these are PRODUCTS rather than platform governance.
    //
    // DIS IS DELIBERATELY NOT IN THIS GROUP. The build spec assumed DIS would
    // "move into MODULES from wherever it is linked today"; it is linked
    // nowhere in this sidebar. DIS is a LAUNCHER TILE pointing at a separate
    // Cloud Run app (lib/launcher/tiles.ts), because it is a large tenant-facing
    // product with its own shell. Synapse 8a is nine read-only SUPERADMIN
    // screens belonging beside Tenants and Stores, so it lives in-shell. Moving
    // DIS in here would mean giving it in-shell routes it does not have.
    heading: "Modules",
    items: [
      {
        href: "/superadmin/synapse",
        label: "Synapse",
        icon: Activity,
        // Same tuple as the cross-tenant Tenants list: Synapse's superadmin
        // screens read every tenant's provisioning and runs, so anything that
        // should not see the tenant list should not see the fleet either.
        requires: { module: "ADMIN", resource: "TENANTS", action: "VIEW", scope: "GLOBAL" },
      },
      {
        // Atlas is PRESENT AND DISABLED on purpose (D3/N4): the navigation shape
        // is settled now so nobody wonders whether it was forgotten. It routes to
        // a static page and fetches NOTHING — an endpoint returning empty is
        // indistinguishable from one that is broken, and this project has removed
        // several artifacts of exactly that kind.
        href: "/superadmin/atlas",
        label: "Atlas",
        icon: Map,
        requires: { module: "ADMIN", resource: "TENANTS", action: "VIEW", scope: "GLOBAL" },
      },
    ],
  },
  {
    heading: "Compliance",
    items: [
      {
        href: "/superadmin/audit",
        label: "Audit Log",
        icon: FileText,
        requires: { module: "ADMIN", resource: "AUDIT_LOG", action: "VIEW" },
      },
    ],
  },
];
