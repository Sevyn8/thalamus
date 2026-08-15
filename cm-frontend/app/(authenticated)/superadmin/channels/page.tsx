"use client";

import { useMemo } from "react";
import { formatDistanceToNow } from "date-fns";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { EmptyState } from "@/components/shared/EmptyState";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { hasPermission } from "@/lib/auth/permissions-check";
import { usePlatformChannels } from "@/lib/hooks/use-channels";
import { useTenants } from "@/lib/hooks/use-tenants";
import { ApiError } from "@/lib/api/client";

// The operator's fleet view of channel connection state.
//
// WHY IT EXISTS: so a blocked or missing delivery is EXPLICABLE. When a tenant
// says nothing reached their customers, the first question is whether a channel
// was ever connected, and this is the only place that answers it without anyone
// reading a credential.
//
// IT SHOWS STATE AND THE SECRET'S NAME, NEVER A VALUE. That is not restraint
// exercised here; it is the shape of the wire. PlatformChannelConnectionRead is
// ChannelConnectionRead plus tenant_id, and neither has a field a credential
// could travel in, because cm-backend cannot read one back.

function orDash(value: string | null | undefined) {
  if (value === null || value === undefined || value === "") return "-";
  return value;
}

function whenever(iso: string | null | undefined) {
  if (!iso) return "-";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "-";
  return `${formatDistanceToNow(parsed)} ago`;
}

export default function PlatformChannelsPage() {
  const snapshot = useAuthSnapshot();
  const canView = hasPermission(
    snapshot,
    "ADMIN",
    "CHANNELS",
    "VIEW",
    "GLOBAL",
  );

  const channels = usePlatformChannels({ enabled: canView });

  // THE WIRE CARRIES tenant_id AND NO TENANT NAME. A fleet table of bare UUIDs
  // cannot serve the purpose above, so the names come from the tenants list the
  // same operator can already read, and the UUID is the fallback whenever a
  // tenant is missing from that list. The fallback is not decoration: the list
  // is paginated and a terminated tenant may not appear in it, and showing a
  // blank cell there would read as "no tenant" rather than "name not to hand".
  const tenants = useTenants({ limit: 200 }, { enabled: canView });

  const tenantNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const t of tenants.data?.items ?? []) map.set(t.id, t.name);
    return map;
  }, [tenants.data]);

  if (!snapshot) {
    return (
      <div className="flex flex-col gap-6 p-6">
        <Skeleton variant="card" className="h-40" />
      </div>
    );
  }

  if (!canView) {
    return (
      <div className="flex flex-col gap-6 p-6">
        <EmptyState
          title="Not available for your account"
          body="Viewing channel connections across tenants needs a role that carries it."
        />
      </div>
    );
  }

  // Expected while the channels routes are absent from the deployed cm-backend
  // image. Named as such rather than reported as a failure of the fleet.
  const notDeployed =
    channels.error instanceof ApiError && channels.error.status === 404;

  const items = channels.data?.items ?? [];

  return (
    <div className="flex flex-col gap-6 p-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-display">Sending channels</h1>
        <p className="text-sm text-muted-foreground">
          Which tenants have configured which channels, and the name of the
          secret holding each credential. Sevyn8 cannot read a tenant&apos;s
          credential, so no value appears here or anywhere else.
        </p>
      </div>

      <div className="rounded-md border border-border bg-surface p-4 text-sm">
        <p className="text-body-strong">Nothing sends over these yet.</p>
        <p className="mt-1 text-muted-foreground">
          A connection records that a tenant stored a credential. There is no
          adapter to deliver over it, so every row stays in the state{" "}
          <span className="font-mono">pending</span>.
        </p>
      </div>

      {channels.isLoading ? (
        <Skeleton variant="card" className="h-48" />
      ) : notDeployed ? (
        <ErrorInline
          title="Not available yet"
          message="This surface is deployed ahead of the service that answers it. No tenant configuration is affected."
        />
      ) : channels.error ? (
        <ErrorInline
          message="Could not load channel connections."
          onRetry={() => channels.refetch()}
        />
      ) : items.length === 0 ? (
        <EmptyState
          title="No tenant has configured a channel"
          body="Connections appear here as tenants save them."
        />
      ) : (
        <div className="overflow-x-auto rounded-md border border-border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Tenant</TableHead>
                <TableHead>Channel</TableHead>
                <TableHead>Provider</TableHead>
                <TableHead>Sending identity</TableHead>
                <TableHead>State</TableHead>
                <TableHead>Stored secret name</TableHead>
                <TableHead>Last saved</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((c) => (
                <TableRow key={`${c.tenant_id}-${c.channel}`}>
                  <TableCell className="font-medium">
                    {tenantNames.get(c.tenant_id) ?? (
                      <span className="font-mono text-caption break-all">
                        {c.tenant_id}
                      </span>
                    )}
                  </TableCell>
                  <TableCell>{orDash(c.channel)}</TableCell>
                  <TableCell>{orDash(c.provider)}</TableCell>
                  <TableCell>{orDash(c.sending_identity)}</TableCell>
                  <TableCell>{orDash(c.status)}</TableCell>
                  <TableCell className="font-mono text-caption break-all">
                    {orDash(c.secret_ref)}
                  </TableCell>
                  <TableCell>{whenever(c.updated_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
