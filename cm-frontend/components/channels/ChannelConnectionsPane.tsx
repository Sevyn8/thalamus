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

// The tenant's own connection state. State and the secret's NAME, never a value,
// because the wire carries no value to render.
//
// EVERY NULL RENDERS AS AN EXPLICIT DASH. A blank cell where secret_ref is null
// reads as "no credential stored", which is a claim this component cannot make:
// null means the column is empty in the row we were given, and the reason is not
// on the wire either.

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
            <TableHead>Stored secret name</TableHead>
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
              {/* The NAME of the secret. Shown because it is what makes a
                  support conversation about a specific stored credential
                  possible without anyone reading the credential. */}
              <TableCell className="font-mono text-caption break-all">
                {orDash(c.secret_ref)}
              </TableCell>
              <TableCell>{whenever(c.updated_at)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
