"use client";

import { formatDistanceToNow } from "date-fns";
import { FileText } from "lucide-react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { UploadStatusChip } from "@/components/dis/chips/UploadStatusChip";
import { cn } from "@/lib/utils";
import type { Upload } from "@/types/dis";

type Props = {
  uploads: Upload[];
  onSelect: (id: string) => void;
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function UploadsTable({ uploads, onSelect }: Props) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="px-3 text-label text-muted-foreground">File</TableHead>
          <TableHead className="text-label text-muted-foreground">Tenant</TableHead>
          <TableHead className="text-label text-muted-foreground">Template</TableHead>
          <TableHead className="text-label text-muted-foreground text-right">Rows</TableHead>
          <TableHead className="text-label text-muted-foreground">Status</TableHead>
          <TableHead className="text-label text-muted-foreground">Uploaded by</TableHead>
          <TableHead className="text-label text-muted-foreground">When</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {uploads.map((u) => (
          <TableRow
            key={u.id}
            onClick={() => onSelect(u.id)}
            className={cn("cursor-pointer")}
          >
            <TableCell className="px-3 py-3">
              <div className="flex items-center gap-3">
                <span
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground"
                  aria-hidden="true"
                >
                  <FileText className="h-4 w-4" />
                </span>
                <div className="flex min-w-0 flex-col">
                  <span className="truncate text-sm font-medium">{u.file_name}</span>
                  <span className="truncate text-xs text-muted-foreground">
                    {formatBytes(u.file_size_bytes)}
                  </span>
                </div>
              </div>
            </TableCell>
            <TableCell>
              <span className="text-sm">{u.tenant_name}</span>
            </TableCell>
            <TableCell>
              {u.template_name ? (
                <span className="text-sm">{u.template_name}</span>
              ) : (
                <span className="text-sm text-muted-foreground">Ad-hoc</span>
              )}
            </TableCell>
            <TableCell className="text-right">
              {u.rows_ingested === null ? (
                <span className="text-sm text-muted-foreground">—</span>
              ) : (
                <span className="text-sm tabular-nums">
                  {u.rows_ingested.toLocaleString()}
                </span>
              )}
            </TableCell>
            <TableCell>
              <UploadStatusChip status={u.status} />
            </TableCell>
            <TableCell>
              <span className="text-sm text-muted-foreground">{u.uploaded_by_name}</span>
            </TableCell>
            <TableCell>
              <span className="text-xs text-muted-foreground">
                {formatDistanceToNow(new Date(u.uploaded_at), { addSuffix: true })}
              </span>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
