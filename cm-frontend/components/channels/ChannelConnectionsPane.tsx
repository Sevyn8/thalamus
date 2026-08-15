"use client";

import { formatDistanceToNow } from "date-fns";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/components/shared/EmptyState";
import type { ChannelConnectionRead } from "@/lib/api/channels";

// The tenant's own connection state. Never a credential value, because the wire carries none,
// and NO LONGER THE SECRET'S NAME EITHER: that column moved to operators only. See the note at
// the table head for why a tenant cannot use it and an operator can.
//
// EVERY NULL RENDERS AS AN EXPLICIT DASH. A blank cell reads as "not configured", which is a
// claim this component cannot make: null means the column is empty in the row we were given,
// and the reason is not on the wire either.

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

export function ChannelConnectionsPane({
  connections,
}: {
  connections: ChannelConnectionRead[];
}) {
  if (connections.length === 0) {
    return (
      <EmptyState
        title="No channel configured yet"
        body="Once you save a channel below, its connection state appears here."
      />
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Channel</TableHead>
            <TableHead>Provider</TableHead>
            <TableHead>Sending identity</TableHead>
            <TableHead>State</TableHead>
            {/* NO "Stored secret name" COLUMN HERE, AND THERE IS ONE ON THE OPERATOR SURFACE.
                It held the Secret Manager secret id, axon-channel-{tenant_uuid}-{channel}. A
                tenant can do nothing with it: they cannot open it, name it in a support request
                more usefully than by naming the channel, and it puts our internal naming and
                their own tenant uuid on their settings page. An operator uses it to correlate a
                row with a vault entry, so it stays at superadmin/channels. */}
            <TableHead>Last saved</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {connections.map((c) => (
            <TableRow key={`${c.channel}-${c.provider}`}>
              <TableCell className="font-medium">{c.channel}</TableCell>
              <TableCell>{orDash(c.provider)}</TableCell>
              <TableCell>{orDash(c.sending_identity)}</TableCell>
              <TableCell>{orDash(c.status)}</TableCell>
              <TableCell>{whenever(c.updated_at)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
