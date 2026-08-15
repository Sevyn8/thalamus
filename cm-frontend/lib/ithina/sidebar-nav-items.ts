import {
  Activity,
  Boxes,
  Building2,
  FileText,
  LayoutDashboard,
  Network,
  Send,
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
      {
        // The operator's fleet view of tenant sending-channel connections.
        // GLOBAL scope, matching the endpoint it reads (GET /channels/platform
        // pins audience PLATFORM). Because hasPermission matches the scope
        // exactly and does not cascade, this hides for every tenant persona
        // without a special case; a tenant's own channels live at
        // /my-ithina/channels, reached from the dashboard card.
        href: "/superadmin/channels",
        label: "Sending Channels",
        icon: Send,
        requires: { module: "ADMIN", resource: "CHANNELS", action: "VIEW", scope: "GLOBAL" },
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
      // THE ATLAS ENTRY WAS HERE AND IS REMOVED (Axon slice 3). D3/N4 argued for
      // keeping it present and disabled so the navigation shape was settled and
      // nobody wondered whether Atlas had been forgotten. That argument was right
      // WHILE ATLAS WAS NEXT IN LINE.
      //
      // Atlas is now DEFERRED INDEFINITELY. A permanent entry stops reading as
      // "coming" and starts reading as "in progress" about something nobody is
      // building, which misinforms every operator who sees it. The reason to show
      // it and the reason to remove it are the same reason: the nav should say
      // what is true.
      //
      // THE PAGE ITSELF IS KEPT, at /superadmin/atlas, reachable by URL only.
      // Removing a nav entry and removing a route are different changes, and the
      // page states its own status. Nothing else about Atlas was deleted.
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
