"use client";

import { motion } from "framer-motion";
import { MoreVertical } from "lucide-react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { StatusChip, TierChip } from "@/components/shared/Chips";
import { initials, avatarTone } from "@/lib/utils/initials";
import { cn } from "@/lib/utils";
import type { Tenant } from "@/types/api";

function formatIndustry(industry: string | null): string {
  if (!industry) return "—";
  return industry
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatMRR(usd: string | null): string {
  if (!usd) return "—";
  const n = Number(usd);
  if (Number.isNaN(n)) return "—";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

export type TenantCardProps = {
  tenant: Tenant;
  onSelect: () => void;
};

export function TenantCard({ tenant, onSelect }: TenantCardProps) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
    >
    <Card
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className="cursor-pointer transition-colors duration-150 ease-out hover:bg-surface-raised hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
    >
      <CardHeader className="flex flex-row items-start gap-3">
        <span
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-sm font-semibold",
            avatarTone(tenant.name),
          )}
          aria-hidden="true"
        >
          {initials(tenant.name)}
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <div className="truncate text-sm font-semibold">{tenant.name}</div>
          <div className="truncate text-xs text-muted-foreground">
            {formatIndustry(tenant.industry)}
            {tenant.country ? ` · ${tenant.country}` : ""}
          </div>
        </div>
        <button
          type="button"
          aria-label="Tenant actions"
          className="invisible -mr-1 -mt-1 rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          onClick={(e) => e.stopPropagation()}
        >
          <MoreVertical className="h-4 w-4" />
        </button>
      </CardHeader>

      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {tenant.tier ? <TierChip tier={tenant.tier} /> : null}
          <StatusChip status={tenant.status} />
        </div>

        <Separator />

        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            <span className="font-medium text-foreground">
              {tenant.num_stores.toLocaleString()}
            </span>{" "}
            stores
          </span>
          <span>
            <span className="font-medium text-foreground">
              {tenant.num_users_active.toLocaleString()}
            </span>{" "}
            users
          </span>
          <span>
            <span className="font-medium text-foreground">
              {formatMRR(tenant.monthly_revenue_usd)}
            </span>{" "}
            MRR
          </span>
        </div>

        <Separator />

        <div className="flex flex-wrap gap-1.5">
          {tenant.modules.slice(0, 4).map((m) => (
            <span
              key={m.code}
              className="inline-flex items-center rounded-md bg-zinc-100 text-zinc-700 ring-zinc-300 px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset dark:bg-zinc-500/10 dark:text-zinc-300 dark:ring-zinc-500/20"
            >
              {m.name}
            </span>
          ))}
          {tenant.modules.length > 4 ? (
            <span
              className="inline-flex items-center rounded-md bg-zinc-100/60 text-zinc-600 ring-zinc-300 px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset dark:bg-zinc-500/5 dark:text-zinc-400 dark:ring-zinc-500/20"
              aria-label={`${tenant.modules.length - 4} more modules`}
            >
              +{tenant.modules.length - 4}
            </span>
          ) : null}
        </div>
      </CardContent>
    </Card>
    </motion.div>
  );
}
