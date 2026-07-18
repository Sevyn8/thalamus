"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { formatDistanceToNow } from "date-fns";
import { PlusCircle } from "lucide-react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { SourceStatusChip } from "@/components/dis/chips/SourceStatusChip";
import { StreamDomainChip } from "@/components/dis/chips/StreamDomainChip";
import { StreamHealthChip } from "@/components/dis/chips/StreamHealthChip";
import { SystemKindChip } from "@/components/dis/chips/SystemKindChip";
import { cn } from "@/lib/utils";
import type { Source, Stream } from "@/types/dis";

// Phase 5e.9: unified Sources & streams fleet view. Persistent nested
// table — source rows are bold parent entries; their streams render
// indented underneath with a left-border lineage guide. The pattern
// echoes the per-source Streams tab on /dis/sources/[id] (5e.4c) but
// at fleet scope. Single header row with mixed column semantics:
// some columns (Domain, Health, Last run) only apply to stream rows;
// the source row shows them as muted dashes.

type Group = {
  source: Source;
  streams: Stream[];
};

type Props = {
  groups: Group[];
};

export function UnifiedSourcesStreamsTable({ groups }: Props) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="px-3 text-label text-muted-foreground">
            Source / Stream
          </TableHead>
          <TableHead className="text-label text-muted-foreground">System</TableHead>
          <TableHead className="text-label text-muted-foreground">Status</TableHead>
          <TableHead className="text-label text-muted-foreground">Domain</TableHead>
          <TableHead className="text-label text-muted-foreground">Health</TableHead>
          <TableHead className="text-label text-muted-foreground">Last run</TableHead>
          <TableHead className="text-label text-muted-foreground">Tenant</TableHead>
          <TableHead className="text-label text-muted-foreground" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {groups.map((group, i) => (
          <SourceGroup
            key={group.source.id}
            group={group}
            isFirst={i === 0}
          />
        ))}
      </TableBody>
    </Table>
  );
}

function SourceGroup({ group, isFirst }: { group: Group; isFirst: boolean }) {
  const router = useRouter();
  const { source, streams } = group;

  return (
    <>
      <TableRow
        onClick={() => router.push(`/dis/sources/${source.id}`)}
        className={cn(
          "cursor-pointer bg-card/30 hover:bg-surface-raised",
          !isFirst && "border-t-2 border-border-strong",
        )}
      >
        <TableCell className="px-3 py-3">
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-sm font-semibold">{source.name}</span>
            <span className="text-micro text-muted-foreground">
              {streams.length} {streams.length === 1 ? "stream" : "streams"}
            </span>
          </div>
        </TableCell>
        <TableCell>
          <SystemKindChip type={source.type} />
        </TableCell>
        <TableCell>
          <SourceStatusChip status={source.status} />
        </TableCell>
        <TableCell>
          <span className="text-xs text-muted-foreground">—</span>
        </TableCell>
        <TableCell>
          <span className="text-xs text-muted-foreground">—</span>
        </TableCell>
        <TableCell>
          <span className="text-xs text-muted-foreground">—</span>
        </TableCell>
        <TableCell>
          <span className="text-sm">{source.tenant_name}</span>
        </TableCell>
        <TableCell
          className="text-right"
          onClick={(e) => e.stopPropagation()}
        >
          <Link
            href={`/dis/streams/new?source=${source.id}`}
            className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
          >
            <PlusCircle className="h-3 w-3" aria-hidden="true" />
            Add stream
          </Link>
        </TableCell>
      </TableRow>
      {streams.map((stream) => (
        <TableRow
          key={stream.id}
          onClick={() => router.push(`/dis/streams/${stream.id}`)}
          className="cursor-pointer"
        >
          <TableCell className="px-3 py-3">
            {/* Indent guide — left border + padding gives the visual
                lineage. Stream name is regular weight; muted prefix
                arrow signals child-of-source. */}
            <div className="flex items-center gap-2 pl-4 border-l-2 border-border ml-2">
              <span className="text-muted-foreground text-xs">↳</span>
              <span className="truncate text-sm">{stream.name}</span>
            </div>
          </TableCell>
          <TableCell>
            <span className="text-xs text-muted-foreground">inherited</span>
          </TableCell>
          <TableCell>
            <SourceStatusChip status={stream.status} />
          </TableCell>
          <TableCell>
            <StreamDomainChip domain={stream.domain} />
          </TableCell>
          <TableCell>
            <StreamHealthChip health={stream.health} />
          </TableCell>
          <TableCell>
            {stream.last_run_at ? (
              <span className="text-xs text-muted-foreground">
                {formatDistanceToNow(new Date(stream.last_run_at), {
                  addSuffix: true,
                })}
              </span>
            ) : (
              <span className="text-xs text-muted-foreground">Never</span>
            )}
          </TableCell>
          <TableCell>
            <span className="text-sm">{stream.tenant_name}</span>
          </TableCell>
          <TableCell />
        </TableRow>
      ))}
    </>
  );
}
