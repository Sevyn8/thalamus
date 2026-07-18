"use client";

import { ScrollText } from "lucide-react";

import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { Skeleton } from "@/components/shared/Skeleton";
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AuditActivityRow } from "./AuditActivityRow";
import type { AuditActivityListItem } from "@/lib/api/audit";

export type AuditActivitiesTableProps = {
  rows: AuditActivityListItem[];
  isLoading: boolean;
  isError: boolean;
  errorMessage?: string;
  onRetry?: () => void;
  showScope: boolean;
  showTenant: boolean;
  onSelectRow: (id: string) => void;
};

export function AuditActivitiesTable({
  rows,
  isLoading,
  isError,
  errorMessage,
  onRetry,
  showScope,
  showTenant,
  onSelectRow,
}: AuditActivitiesTableProps) {
  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton variant="row" count={6} />
      </div>
    );
  }

  if (isError) {
    return (
      <ErrorInline
        message={errorMessage ?? "Could not load audit activities."}
        onRetry={onRetry}
      />
    );
  }

  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<ScrollText />}
        title="No audit activities yet"
        body="Activity rows appear here as users create, update, and access resources."
      />
    );
  }

  return (
    <div className="rounded-md border border-border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-label text-foreground-muted">
              Timestamp
            </TableHead>
            <TableHead className="text-label text-foreground-muted">
              Actor
            </TableHead>
            <TableHead className="text-label text-foreground-muted">
              Action
            </TableHead>
            <TableHead className="text-label text-foreground-muted">
              Resource
            </TableHead>
            <TableHead className="text-label text-foreground-muted">
              Type
            </TableHead>
            <TableHead className="text-label text-foreground-muted">
              Result
            </TableHead>
            {showScope ? (
              <TableHead className="text-label text-foreground-muted">
                Scope
              </TableHead>
            ) : null}
            {showTenant ? (
              <TableHead className="text-label text-foreground-muted">
                Tenant
              </TableHead>
            ) : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <AuditActivityRow
              key={row.id}
              row={row}
              showScope={showScope}
              showTenant={showTenant}
              onSelect={onSelectRow}
            />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
