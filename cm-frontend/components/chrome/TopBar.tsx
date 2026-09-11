"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { NotificationsButton } from "./NotificationsButton";
import { UserMenu } from "./UserMenu";

// There is no ProductSwitcher dropdown here: the launcher at
// /my-sevyn8 is the canonical product-discovery surface, so a
// standalone "Platform" badge would be redundant with the sidebar.

// Top-of-page search is hidden — no global-search backend
// implementation. Placeholder strings are retained for when search
// returns (persona-aware framing). When re-adding the input, also
// restore `useAuthSnapshot` from "@/lib/auth/auth-cache" to drive the
// placeholder selection.
export const SEARCH_PLACEHOLDER_PLATFORM = "Search tenants, users, roles…";
export const SEARCH_PLACEHOLDER_TENANT = "Search users, roles, stores…";

export function TopBar() {
  return (
    // ver2's topbar (index.css:239-255): sticky, z-20, SOLID --surface, bottom border.
    // The backdrop-blur and bg-background/95 translucency are gone deliberately — ver2's
    // chrome is opaque, and a blurred bar reads as a different material from a solid one,
    // which is exactly the kind of difference that makes two apps look unrelated. Recorded
    // in the spec as an adopted convention.
    <header className="sticky top-0 z-20 border-b border-border bg-surface">
      {/* THE SPECTRUM (index.css:246-249). A 3px child ABOVE the bar, not a border: it is
          full-bleed across the topbar and therefore across the content column only — the
          sidebar is a sibling, so the strip stops at its edge, exactly as in ver2's grid.
          Three stops here, horizontal; the sidebar's active rail is a DIFFERENT gradient
          (two stops, vertical) and the two must not be conflated. */}
      <div
        aria-hidden="true"
        className="h-[3px] bg-[linear-gradient(90deg,var(--cyan),var(--primary),var(--magenta))]"
      />
      <div className="flex h-14 items-center gap-4 px-6">
        <div className="flex min-w-0 items-center gap-3">
          <Link
            href="/my-sevyn8"
            aria-label="Back to My Sevyn8 launcher"
            className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[0.8rem] font-medium text-muted-foreground transition-colors duration-150 ease-out hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
            <span className="hidden sm:inline">My Sevyn8</span>
          </Link>
        </div>

        <div className="ml-auto flex items-center gap-2">
          {/* Global search re-add target — restore <Input> block here
            when search ships. Use SEARCH_PLACEHOLDER_* constants. */}
          <NotificationsButton />
          <UserMenu />
        </div>
      </div>
    </header>
  );
}
