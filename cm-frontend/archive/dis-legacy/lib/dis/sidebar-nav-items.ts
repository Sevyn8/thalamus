import {
  Activity,
  Bell,
  BookOpen,
  BookText,
  Brain,
  CheckCircle2,
  CircleDot,
  Clock,
  FileSpreadsheet,
  GitCompare,
  History,
  LayoutDashboard,
  PlusCircle,
  Receipt,
  ScrollText,
  ServerCog,
  Settings,
  Upload,
  Workflow,
} from "lucide-react";

import type { NavGroup } from "@/components/chrome/Sidebar";

// DIS sidebar nav structure. Mirrors lib/ithina/sidebar-nav-items.ts;
// both feed the shared Sidebar component, swapped at the layout layer
// based on active product. Source: docs/dis-surface-map.md "Sidebar nav
// structure" section. v2-marked items (Catalog, Warehouse, Migrations,
// Templates marketplace, Composer, BigQuery, Forecast, dashboard
// builder) are excluded from v1 — they will be added when their feature
// chunks land in Phase 5c.
//
// Two named exports because ADMIN sits between INSIGHTS and HELP per
// surface map; rather than splice a base array, we declare both views
// in full and let DisSidebar pick on persona userType.

// Phase 5d.8: Overview's "Dashboard" entry now points to the real
// per-tenant dashboard at /dis/dashboards (Phase 5c.8e1). The former
// "Insights" group housed the same surface under a duplicate
// "Dashboards" label — deleted. Label is "Dashboard" (singular) per
// the visible-affordance perspective; URL stays plural per the
// implementation file path. Routing has only ever resolved to one
// real dashboard.
const overview: NavGroup = {
  heading: "Overview",
  items: [
    { href: "/dis/dashboards", label: "Dashboard", icon: LayoutDashboard },
  ],
};

const ingestion: NavGroup = {
  heading: "Ingestion",
  items: [
    { href: "/dis/sources/new", label: "Add source", icon: PlusCircle },
    // Phase 5e.9: "Sources" + "Streams" consolidated into the single
    // "Sources & streams" entry pointing at the unified /dis/sources
    // fleet view. /dis/streams persists as a permanent redirect for
    // legacy bookmarks. Workflow icon retained (it telegraphs "data
    // pipeline" better than Plug's "credential" semantic).
    { href: "/dis/sources", label: "Sources & streams", icon: Workflow },
    { href: "/dis/uploads", label: "Uploads", icon: Upload },
    { href: "/dis/templates", label: "Templates", icon: FileSpreadsheet },
    { href: "/dis/runs", label: "Runs", icon: Activity },
    { href: "/dis/backfills", label: "Backfills", icon: History },
  ],
};

const quality: NavGroup = {
  heading: "Quality",
  items: [
    { href: "/dis/validation", label: "Validation", icon: CheckCircle2 },
    { href: "/dis/validation/drift", label: "Schema drift", icon: GitCompare },
    { href: "/dis/freshness", label: "Freshness", icon: Clock },
    { href: "/dis/alerts", label: "Alerts", icon: Bell },
  ],
};

const governance: NavGroup = {
  heading: "Governance",
  items: [
    { href: "/dis/canonical-schema", label: "Canonical schema", icon: BookOpen },
  ],
};

// Phase 5d.8: "Insights" group deleted. Its "Dashboards" entry was
// a duplicate of Overview's Dashboard pointing at the same real
// surface. "Cost" moved into Admin (below) where it belongs —
// /dis/cost is PLATFORM-only at the page level; Admin is a
// PLATFORM-only sidebar group, so visibility now matches gating
// without any per-item special-case logic.
// Phase 5e.2: "Canonical schema (edit)" entry removed. Canonical-schema
// edit + browse consolidated under /dis/canonical-schema/[domain] with
// inline RBAC gating of admin affordances (Add field / Bump version /
// per-row Edit + Soft-delete / History tab). Governance entry above is
// now the single sidebar pointer for both personas.
// Phase 5e.10a: "Provisioning" entry retired. Tenant lifecycle
// (creation, suspension, termination) is platform-superadmin scope;
// the module-side surface duplicated platform authority and is gone.
// Admin group now 2 entries (Fleet + LLM ops) + Cost.
const admin: NavGroup = {
  heading: "Admin",
  items: [
    { href: "/dis/admin/fleet", label: "Fleet health", icon: ServerCog },
    { href: "/dis/admin/llm-ops", label: "LLM operations", icon: Brain },
    { href: "/dis/cost", label: "Cost", icon: Receipt },
  ],
};

const help: NavGroup = {
  heading: "Help",
  items: [
    // Phase 5e.7a: "Onboarding" entry retired alongside the
    // /dis/onboarding wizard — the wizard captured intent that was
    // never consumed (no source ever got created from the captured
    // payload) and the canonical-mapping step was read-only tease.
    // First-time tenants discover via "Add source" entry + the
    // sources list emptiness pattern, not a separate wizard.
    { href: "/dis/docs", label: "Docs", icon: BookText },
    { href: "/dis/status", label: "Status", icon: CircleDot },
    { href: "/dis/changelog", label: "Changelog", icon: ScrollText },
    { href: "/dis/settings", label: "Settings", icon: Settings },
  ],
};

export const disTenantSidebarNavItems: NavGroup[] = [
  overview,
  ingestion,
  quality,
  governance,
  help,
];

export const disPlatformSidebarNavItems: NavGroup[] = [
  overview,
  ingestion,
  quality,
  governance,
  admin,
  help,
];
