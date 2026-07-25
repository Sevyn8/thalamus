"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  type LucideIcon,
} from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { IthinaLogo } from "@/components/chrome/IthinaLogo";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import {
  hasPermission,
  type PermissionScope,
} from "@/lib/auth/permissions-check";
import { cn } from "@/lib/utils";

const COLLAPSED_KEY = "ithina_sidebar_collapsed";

// Component-API contract for sidebar navigation. Co-located with the
// Sidebar component since it owns the rendering shape; product-specific
// constants (lib/ithina/sidebar-nav-items.ts; future
// lib/dis/sidebar-nav-items.ts) import these types and the layout
// passes the right constant per active product.
//
// Phase 5g.1: optional `requires` tuple per item. Sidebar filters items
// against the cached /me/permissions grant list via `hasPermission`.
// Items without `requires` are always visible (e.g. Dashboard).
// Fail-closed during boot: items with `requires` stay hidden until
// /me/permissions resolves, by design.
export type NavRequires = {
  module: string;
  resource: string;
  action: string;
  scope?: PermissionScope;
};
export type NavItem = {
  href: string;
  label: string;
  // Phase 5g.1.6: optional label override for TENANT personas.
  // When the cosmetic framing of a label is PLATFORM-leaky (e.g.
  // "Platform Dashboard"), provide the tenant-side framing here
  // ("Dashboard"); Sidebar resolves the right one per snapshot.
  // PLATFORM always sees `label`; TENANT sees `labelTenant ?? label`.
  labelTenant?: string;
  icon: LucideIcon;
  requires?: NavRequires;
};
export type NavGroup = { heading: string; items: NavItem[] };

export type SidebarProps = {
  navGroups: NavGroup[];
};

export function Sidebar({ navGroups }: SidebarProps) {
  const pathname = usePathname() ?? "";
  const snapshot = useAuthSnapshot();
  const [collapsed, setCollapsed] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  // Filter items by permission. Groups with no visible items are
  // dropped entirely so empty section headings don't render.
  const visibleGroups = navGroups
    .map((g) => ({
      ...g,
      items: g.items.filter(
        (i) =>
          !i.requires ||
          hasPermission(
            snapshot,
            i.requires.module,
            i.requires.resource,
            i.requires.action,
            i.requires.scope,
          ),
      ),
    }))
    .filter((g) => g.items.length > 0);

  // Cosmetic branding: PLATFORM personas see "Superadmin Console";
  // TENANT-OWNER personas see their tenant name + "Admin". Text-only
  // — access control is the permission filter above, not this.
  const persona = snapshot?.user;
  const isTenantBrand = persona?.userType === "TENANT";
  const brandLine =
    isTenantBrand && persona?.tenantName
      ? persona.tenantName
      : "Sevyn8";
  const brandSub = isTenantBrand ? "Admin" : "Superadmin Console";

  useEffect(() => {
    const saved = window.localStorage.getItem(COLLAPSED_KEY);
    setCollapsed(saved === "1");
    setHydrated(true);
  }, []);

  function toggle() {
    setCollapsed((prev) => {
      const next = !prev;
      window.localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
      return next;
    });
  }

  // Cmd+\ (Mac) / Ctrl+\ (Win/Linux) toggles the sidebar.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "\\" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        toggle();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <aside
      data-collapsed={collapsed}
      className={cn(
        "sticky top-0 flex h-screen shrink-0 flex-col border-r border-border bg-sidebar text-sidebar-foreground transition-[width] duration-150",
        collapsed ? "w-16" : "w-60",
        !hydrated && "invisible",
      )}
    >
      {/* Phase 5d.1: logo + brand block routes to My Ithina launcher.
          Same Sidebar primitive used by both Ithina + DIS layouts, so
          this single Link gives both products the back-to-launcher
          affordance via the logo. */}
      <Link
        href="/my-ithina"
        aria-label="Go to My Sevyn8 launcher"
        className="flex items-center gap-2 px-4 py-4 transition-colors duration-150 ease-out hover:bg-sidebar-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        {/* Phase 5d.7: real Ithina brandmark replaces the prior
            "I"-letterform placeholder. Logo on transparent
            background; the SVG's hardcoded brand blue renders
            cleanly on both light + dark sidebar backgrounds. */}
        <IthinaLogo size={32} />

        {!collapsed ? (
          <div className="flex min-w-0 flex-col leading-tight">
            <span className="truncate text-sm font-semibold tracking-tight">
              {brandLine}
            </span>
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
              {brandSub}
            </span>
          </div>
        ) : null}
      </Link>

      <nav className="flex flex-1 flex-col gap-4 overflow-y-auto px-2 py-2">
        {visibleGroups.map((group) => (
          <div key={group.heading}>
            {!collapsed ? (
              <div className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {group.heading}
              </div>
            ) : null}
            <ul className="flex flex-col gap-0.5">
              {group.items.map((item) => {
                const active =
                  pathname === item.href || pathname.startsWith(`${item.href}/`);
                const Icon = item.icon;
                const displayLabel =
                  isTenantBrand && item.labelTenant ? item.labelTenant : item.label;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      title={collapsed ? displayLabel : undefined}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors duration-150 ease-out",
                        active
                          ? "bg-sidebar-accent text-sidebar-accent-foreground"
                          : "text-sidebar-foreground/80 hover:bg-sidebar-accent/40 hover:text-sidebar-foreground",
                        collapsed && "justify-center px-2",
                      )}
                    >
                      <Icon className="h-4 w-4 shrink-0" />
                      {!collapsed ? <span className="truncate">{displayLabel}</span> : null}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <Tooltip>
        <TooltipTrigger
          render={
            <button
              type="button"
              onClick={toggle}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              className="m-2 flex h-9 items-center justify-center gap-2 rounded-md border border-border-strong bg-sidebar-accent/20 text-xs text-muted-foreground transition-colors duration-150 ease-out hover:bg-surface-raised hover:text-sidebar-foreground"
            />
          }
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : (
            <>
              <ChevronLeft className="h-4 w-4" />
              <span>Collapse</span>
            </>
          )}
        </TooltipTrigger>
        <TooltipContent>
          {collapsed ? "Expand sidebar (⌘\\)" : "Collapse sidebar (⌘\\)"}
        </TooltipContent>
      </Tooltip>
    </aside>
  );
}
