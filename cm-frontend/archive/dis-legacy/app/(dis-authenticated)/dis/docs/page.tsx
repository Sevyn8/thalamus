"use client";

import type { LucideIcon } from "lucide-react";
import { BookOpen, Database, FileCode2, LifeBuoy } from "lucide-react";

import { PageHeader } from "@/components/shared/PageHeader";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// Phase 5c.8f2: documentation hub. Static link list — full docs
// ship with v1 GA. Outbound URLs are deferred (we don't have
// canonical hostnames yet), so each card uses href="#" +
// aria-disabled + a "Coming with v1 GA" tooltip on hover. The
// shape mirrors what the GA page will look like; only the hrefs
// change.

type DocCard = {
  icon: LucideIcon;
  title: string;
  description: string;
};

const DOC_CARDS: DocCard[] = [
  {
    icon: BookOpen,
    title: "DIS overview",
    description:
      "What the Data Ingestion Stack is, where it fits alongside the canonical schema, and how Ithina personas use it day-to-day.",
  },
  {
    icon: Database,
    title: "Canonical schema reference",
    description:
      "Field-level reference for the canonical transaction schema, including required-field rules, versioning policy, and tenant-override semantics.",
  },
  {
    icon: FileCode2,
    title: "API reference",
    description:
      "REST endpoints for DIS sources, runs, validation, alerts, freshness, and per-tenant dashboards. Includes auth and idempotency conventions.",
  },
  {
    icon: LifeBuoy,
    title: "Operator runbook",
    description:
      "Common operator workflows: handling failed runs, escalating data-quality alerts, suspending or terminating a tenant, and reading the LLM-ops cost view.",
  },
];

export default function Page() {
  return (
    <div className="flex flex-col">
      <PageHeader
        title="Docs"
        subtitle="Documentation hub — full docs ship with v1 GA"
      />

      <div className="flex flex-col gap-6 p-6">
        <div className="rounded-md border border-border bg-card/20 p-4">
          <p className="text-body text-foreground-muted">
            The links below are placeholders for the v1 GA documentation
            set. Hover any card to confirm; they will resolve to
            published URLs at GA.
          </p>
        </div>

        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {DOC_CARDS.map((card) => {
            const Icon = card.icon;
            return (
              <li key={card.title}>
                <Tooltip>
                  <TooltipTrigger
                    render={
                      <a
                        href="#"
                        aria-disabled="true"
                        onClick={(e) => e.preventDefault()}
                        className="flex h-full flex-col gap-2 rounded-md border border-border bg-card p-4 transition-colors duration-150 ease-out hover:bg-surface-raised hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      />
                    }
                  >
                    <div className="flex items-center gap-2">
                      <Icon
                        aria-hidden="true"
                        className="h-4 w-4 text-foreground-muted"
                      />
                      <span className="text-subheading text-foreground">
                        {card.title}
                      </span>
                    </div>
                    <p className="text-caption text-foreground-muted">
                      {card.description}
                    </p>
                  </TooltipTrigger>
                  <TooltipContent>Coming with v1 GA</TooltipContent>
                </Tooltip>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
