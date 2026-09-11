"use client";

// Thin product-specific wrapper around the generic Sidebar. Imports the
// Ithina nav constant and forwards it as the navGroups prop, so the
// (server-rendered) authenticated layout doesn't have to import the
// constant itself — function references on the icons would otherwise
// fail to serialize across the server/client boundary at prerender
// time.

import { Sidebar } from "./Sidebar";
import { ithinaSidebarNavItems } from "@/lib/ithina/sidebar-nav-items";

export function IthinaSidebar() {
  return <Sidebar navGroups={ithinaSidebarNavItems} />;
}
