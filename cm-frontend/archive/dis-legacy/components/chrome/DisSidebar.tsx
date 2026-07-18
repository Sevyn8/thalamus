"use client";

// Thin DIS-specific wrapper around the generic Sidebar. Mirrors
// IthinaSidebar's pattern of importing the nav constant inside the
// client tree (Lucide forwardRef icons cannot serialize across the
// server/client boundary at prerender). Picks Tenant or Platform nav
// view based on persona userType from the auth snapshot — the ADMIN
// section appears only for PLATFORM personas, matching the surface
// map's "Anjali sees the full DIS sidebar regardless of any tenant's
// module config; gating applies to tenant users only" rule.

import { Sidebar } from "./Sidebar";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import {
  disPlatformSidebarNavItems,
  disTenantSidebarNavItems,
} from "@/lib/dis/sidebar-nav-items";

export function DisSidebar() {
  const snapshot = useAuthSnapshot();
  const isPlatform = snapshot?.user.userType === "PLATFORM";
  const navGroups = isPlatform ? disPlatformSidebarNavItems : disTenantSidebarNavItems;
  return <Sidebar navGroups={navGroups} />;
}
