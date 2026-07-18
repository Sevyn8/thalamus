import {
  Boxes,
  Building2,
  FileText,
  LayoutDashboard,
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
