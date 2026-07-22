"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { NotificationsButton } from "./NotificationsButton";
import { UserMenu } from "./UserMenu";

// Phase 5d.10: ProductSwitcher dropdown removed. The launcher at
// /my-ithina is now the canonical product-discovery surface; the
// dropdown was a "coexist during rollout" placeholder from 5d.1
// that's now redundant. Decontextualized "Platform" badge dropped
// alongside (it was meaningful next to the dropdown; standalone it
// just labeled the product the user is already in via sidebar).
// Lib/products.ts + lib/feature-flags.ts orphans deleted in the
// same chunk.

// Phase 5g.1.4: top-of-page search hidden — no global-search backend
// implementation. Placeholder strings retained for when search
// returns (persona-aware framing from 5g.1). When re-adding the
// input, also restore `useAuthSnapshot` from "@/lib/auth/auth-cache"
// to drive the placeholder selection.
export const SEARCH_PLACEHOLDER_PLATFORM = "Search tenants, users, roles…";
export const SEARCH_PLACEHOLDER_TENANT = "Search users, roles, stores…";

export function TopBar() {
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-4 border-b border-border bg-background/95 px-6 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <div className="flex min-w-0 items-center gap-3">
        <Link
          href="/my-ithina"
          aria-label="Back to My Cortex launcher"
          className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[0.8rem] font-medium text-muted-foreground transition-colors duration-150 ease-out hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="hidden sm:inline">My Cortex</span>
        </Link>
      </div>

      <div className="ml-auto flex items-center gap-2">
        {/* Global search re-add target — restore <Input> block here
            when search ships. Use SEARCH_PLACEHOLDER_* constants. */}
        <NotificationsButton />
        <UserMenu />
      </div>
    </header>
  );
}
