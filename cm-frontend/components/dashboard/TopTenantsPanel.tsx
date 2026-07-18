"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TierChip } from "@/components/shared/Chips";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { initials, avatarTone } from "@/lib/utils/initials";
import { cn } from "@/lib/utils";
import { useTopTenants } from "@/lib/hooks/use-dashboard";
import type { Tenant } from "@/types/api";

function Row({ tenant }: { tenant: Tenant }) {
  const router = useRouter();
  function open() {
    router.push(`/superadmin/tenants?tenant=${tenant.id}`);
  }
  return (
    <li>
      <button
        type="button"
        onClick={open}
        className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-left transition-colors hover:bg-accent/40"
      >
        <span
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-xs font-semibold",
            avatarTone(tenant.name),
          )}
          aria-hidden="true"
        >
          {initials(tenant.name)}
        </span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm font-medium">{tenant.name}</span>
          <span className="truncate text-xs text-muted-foreground">
            {(tenant.industry ?? "—").toLowerCase().replace(/_/g, " ")}
            {tenant.country ? ` · ${tenant.country}` : ""}
          </span>
        </span>
        <span className="hidden text-right text-xs text-muted-foreground sm:flex sm:flex-col">
          <span>
            <span className="font-medium text-foreground">
              {tenant.num_users_active.toLocaleString()}
            </span>{" "}
            users
          </span>
          <span>
            <span className="font-medium text-foreground">
              {tenant.num_stores.toLocaleString()}
            </span>{" "}
            stores
          </span>
        </span>
        {tenant.tier ? <TierChip tier={tenant.tier} /> : null}
      </button>
    </li>
  );
}

export function TopTenantsPanel() {
  const q = useTopTenants();
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Top tenants by users</CardTitle>
        {/* Phase 5c.partial-deploy.hotfix2: "Demo data" badge
            removed — this section now reads from Sanjeev's real
            /api/v1/tenants endpoint with sort/limit. Recent
            Activity panel still carries the badge until Sanjeev
            ships /audit-logs at Step 6.2. */}
        <Link
          href="/superadmin/tenants"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          Manage all <ArrowRight className="h-3 w-3" />
        </Link>
      </CardHeader>
      <CardContent>
        {q.isLoading ? (
          <Skeleton variant="row" count={5} />
        ) : q.error ? (
          <ErrorInline message="Could not load tenants." onRetry={() => q.refetch()} />
        ) : (
          <ul className="flex flex-col gap-1">
            {q.data?.items.map((t) => <Row key={t.id} tenant={t} />)}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
