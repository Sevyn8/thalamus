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
import { StreamDomainChip } from "@/components/dis/chips/StreamDomainChip";
import { StreamHealthChip } from "@/components/dis/chips/StreamHealthChip";
import { SourceStatusChip } from "@/components/dis/chips/SourceStatusChip";
import { SystemKindChip } from "@/components/dis/chips/SystemKindChip";
import type { Stream } from "@/types/dis";

// Phase 5e.4b: Streams list table. Mirrors SourcesTable shape but
// substitutes columns to surface the multi-stream-per-source case:
// rows show Stream name + parent source line, Domain badge, System
// kind, plus Status / Health / Last run. No bulk selection in 5e.4b —
// stream mutations land in 5e.4d with the AddStreamWizard.

type Props = {
  streams: Stream[];
  onSelect: (id: string) => void;
};

export function StreamsTable({ streams, onSelect }: Props) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="px-3 text-label text-muted-foreground">Stream</TableHead>
          <TableHead className="text-label text-muted-foreground">Domain</TableHead>
          <TableHead className="text-label text-muted-foreground">System</TableHead>
          <TableHead className="text-label text-muted-foreground">Tenant</TableHead>
          <TableHead className="text-label text-muted-foreground">Status</TableHead>
          <TableHead className="text-label text-muted-foreground">Health</TableHead>
          <TableHead className="text-label text-muted-foreground">Last run</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {streams.map((s) => (
          <TableRow
            key={s.id}
            onClick={() => onSelect(s.id)}
            className="cursor-pointer"
          >
            <TableCell className="px-3 py-3">
              <div className="flex min-w-0 flex-col">
                <span className="truncate text-sm font-medium">{s.name}</span>
                <span className="truncate text-xs text-muted-foreground">
                  {s.source_name}
                </span>
              </div>
            </TableCell>
            <TableCell>
              <StreamDomainChip domain={s.domain} />
            </TableCell>
            <TableCell>
              <SystemKindChip type={s.system_kind} />
            </TableCell>
            <TableCell>
              <span className="text-sm">{s.tenant_name}</span>
            </TableCell>
            <TableCell>
              <SourceStatusChip status={s.status} />
            </TableCell>
            <TableCell>
              <StreamHealthChip health={s.health} />
            </TableCell>
            <TableCell>
              {s.last_run_at ? (
                <span className="text-xs text-muted-foreground">
                  {formatDistanceToNow(new Date(s.last_run_at), { addSuffix: true })}
                </span>
              ) : (
                <span className="text-xs text-muted-foreground">Never</span>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
