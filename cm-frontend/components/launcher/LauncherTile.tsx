"use client";

import Link from "next/link";
import type { LucideIcon } from "lucide-react";

import { comingInV1 } from "@/components/shared/ComingInV1Toast";
import { cn } from "@/lib/utils";

// Phase 5d.1: My Ithina launcher tile primitive. Two visual states:
//
//   "available": full-color icon, hoverable card, navigates via
//                 next/link to the tile's href when clicked.
//   "coming-soon": muted icon + label, "Coming Soon" chip, click
//                   fires comingInV1 toast (consistent with the
//                   PageHeader primaryAction pattern).
//   "unmapped": Axon slice 4. A module the server says is enabled and
//                this build has no tile for. Visibly broken on purpose
//                and NOT interactive: there is nowhere to send the user
//                and a "Coming Soon" chip would be a lie, because the
//                module is not coming, it is missing from this image.
//
// Tiles render at a consistent aspect (square-ish ~1:1.1) so a 3-col
// grid reads cleanly across the 2- to 9-tile range Phase 5d.1
// surfaces.

export type LauncherTileState = "available" | "coming-soon" | "unmapped";

export type LauncherTileProps = {
  id: string;
  icon: LucideIcon;
  name: string;
  description: string;
  state: LauncherTileState;
  // Required when state === "available"; ignored otherwise. Strict
  // typing on the call site is easier than a discriminated union for
  // this shape; the 9-entry registry mostly hardcodes both.
  href?: string;
};

export function LauncherTile({
  icon: Icon,
  name,
  description,
  state,
  href,
}: LauncherTileProps) {
  const isAvailable = state === "available";

  // THE VISIBLY-BROKEN TILE. Returned before the shared markup below rather than
  // threaded through it, because almost nothing it needs is shared: no hover
  // affordance, no chip, no click target, and a name that is a module code
  // rather than a product name. Rendering it through the same branches would
  // mean four conditionals to make one card look like something else.
  if (state === "unmapped") {
    return (
      <div
        role="status"
        className="flex h-full flex-col gap-3 rounded-md border border-dashed border-destructive/50 bg-destructive/5 p-5"
      >
        <div className="flex items-center justify-between">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-destructive/10 text-destructive">
            <Icon className="h-5 w-5" aria-hidden="true" />
          </div>
          <span className="rounded-sm bg-destructive/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-destructive ring-1 ring-destructive/30">
            Unavailable
          </span>
        </div>
        <div className="flex flex-1 flex-col gap-1">
          <span className="text-subheading font-mono text-destructive">{name}</span>
          <span className="text-caption text-foreground-muted">{description}</span>
        </div>
      </div>
    );
  }

  const inner = (
    <div
      className={cn(
        "flex h-full flex-col gap-3 rounded-md border p-5 transition-colors duration-150 ease-out",
        isAvailable
          ? "border-border bg-card hover:bg-surface-raised hover:border-border-strong"
          : "border-border bg-card/40",
      )}
    >
      <div className="flex items-center justify-between">
        <div
          className={cn(
            "flex h-10 w-10 items-center justify-center rounded-md",
            isAvailable
              ? "bg-primary/10 text-primary"
              : "bg-muted text-foreground-muted",
          )}
        >
          <Icon className="h-5 w-5" aria-hidden="true" />
        </div>
        {!isAvailable ? (
          <span className="rounded-sm bg-muted px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-foreground-muted ring-1 ring-border">
            Coming Soon
          </span>
        ) : null}
      </div>
      <div className="flex flex-1 flex-col gap-1">
        <span
          className={cn(
            "text-subheading",
            isAvailable ? "text-foreground" : "text-foreground-muted",
          )}
        >
          {name}
        </span>
        <span className="text-caption text-foreground-muted">
          {description}
        </span>
      </div>
    </div>
  );

  if (isAvailable && href) {
    const linkClassName =
      "block h-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-md";

    // Absolute URLs point at a separate deployed app (e.g. DIS). Render a
    // plain anchor navigating in the same tab; next/link is for internal routes.
    const isAbsolute =
      href.startsWith("http://") || href.startsWith("https://");

    if (isAbsolute) {
      return (
        <a
          href={href}
          aria-label={`Open ${name}`}
          className={linkClassName}
        >
          {inner}
        </a>
      );
    }

    return (
      <Link href={href} aria-label={`Open ${name}`} className={linkClassName}>
        {inner}
      </Link>
    );
  }

  return (
    <button
      type="button"
      onClick={() => comingInV1(name)}
      aria-label={`${name}, coming soon`}
      className="block h-full w-full text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-md"
    >
      {inner}
    </button>
  );
}
