"use client";

import Link from "next/link";
import { ArrowRight, Send } from "lucide-react";

// The entry point to /my-ithina/channels for a tenant administrator.
//
// IT DELIBERATELY FETCHES NOTHING. A count of configured channels would need
// GET /api/v1/channels, which is absent from the deployed cm-backend image and
// answers 404 today, so a metric here would put an error state on the dashboard
// of every tenant administrator to display a number nobody asked for. A card
// that navigates does not need to know what it is navigating to.
//
// It is also why this is not a KpiCard: that component's shape is a metric, and
// there is no honest metric to put in it.
//
// The caller decides whether to render this at all. See the dashboard page: the
// gate is hasPermission(ADMIN, CHANNELS, VIEW, TENANT), which does not cascade,
// so a PLATFORM persona holding VIEW.GLOBAL does not see it.

export function ChannelsEntryCard() {
  return (
    <Link
      href="/my-ithina/channels"
      className="group flex items-start gap-4 rounded-md border border-border bg-surface p-4 transition-colors duration-150 ease-out hover:border-border-strong hover:bg-surface-raised"
    >
      <span className="mt-0.5 rounded-md border border-border p-2 text-muted-foreground">
        <Send className="h-4 w-4" aria-hidden="true" />
      </span>
      <span className="flex flex-1 flex-col gap-1">
        <span className="text-subheading">Sending channels</span>
        <span className="text-caption text-muted-foreground">
          Configure the provider credential your organisation sends with. Sevyn8
          stores it and cannot read it back. Nothing is sent yet.
        </span>
      </span>
      <ArrowRight
        className="mt-1 h-4 w-4 text-muted-foreground transition-transform duration-150 ease-out group-hover:translate-x-0.5"
        aria-hidden="true"
      />
    </Link>
  );
}
