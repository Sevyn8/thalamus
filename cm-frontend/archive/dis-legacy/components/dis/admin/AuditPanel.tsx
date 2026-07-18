"use client";

import { useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { EmptyState } from "@/components/shared/EmptyState";
import { Chip, type Tone } from "@/components/shared/Chips";
import { useAuditEvents } from "@/lib/dis/hooks/use-audit-events";
import type { AuditEventListItem } from "@/lib/dis/api/audit-events";

// Phase 5d.6: canonical-schema audit panel. Reverse-chronological
// timeline of canonical-schema events scoped to the current domain.
// Reads from the DIS audit-events store (MSW-backed today; deployed
// endpoint Phase 5e+). Five event types relevant here:
//
//   canonical_schema_edit                 — field property changed
//   canonical_schema_field_added          — field created
//   canonical_schema_version_bumped       — domain version bumped
//   canonical_schema_field_soft_deleted   — field deleted (5d.6)
//   canonical_schema_field_restored       — field restored (5d.6)
//
// canonical_schema_edit events are expandable to show before/after
// diff. Others render summary-only.

const CANONICAL_EVENT_TYPES = [
  "canonical_schema_edit",
  "canonical_schema_field_added",
  "canonical_schema_version_bumped",
  "canonical_schema_field_soft_deleted",
  "canonical_schema_field_restored",
];

const EVENT_LABEL: Record<string, string> = {
  canonical_schema_edit: "Field edited",
  canonical_schema_field_added: "Field added",
  canonical_schema_version_bumped: "Version bumped",
  canonical_schema_field_soft_deleted: "Field deleted",
  canonical_schema_field_restored: "Field restored",
};

const EVENT_TONE: Record<string, Tone> = {
  canonical_schema_edit: "blue",
  canonical_schema_field_added: "green",
  canonical_schema_version_bumped: "violet",
  canonical_schema_field_soft_deleted: "red",
  canonical_schema_field_restored: "amber",
};

const CLASSIFICATION_TONE: Record<string, Tone> = {
  additive: "green",
  breaking: "red",
  neutral: "grey",
};

function formatAbsolute(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toUTCString();
}

function eventSummary(event: AuditEventListItem): string {
  const p = event.payload;
  switch (event.event_type) {
    case "canonical_schema_edit": {
      const fieldId = typeof p.field_id === "string" ? p.field_id : "";
      const changes = (p.changes ?? {}) as Record<string, unknown>;
      const keys = Object.keys(changes);
      const what =
        keys.length === 0
          ? "(no changes captured)"
          : keys.length === 1
            ? `${keys[0]}`
            : `${keys.length} fields`;
      return `${fieldId} — ${what}`;
    }
    case "canonical_schema_field_added": {
      const fieldName = typeof p.field_name === "string" ? p.field_name : "";
      const fieldId = typeof p.field_id === "string" ? p.field_id : "";
      return `${fieldName} (${fieldId})`;
    }
    case "canonical_schema_version_bumped": {
      const prev = typeof p.prev_version === "string" ? p.prev_version : "?";
      const next = typeof p.next_version === "string" ? p.next_version : "?";
      const count = typeof p.change_count === "number" ? p.change_count : 0;
      return `${prev} → ${next} (${count} change${count === 1 ? "" : "s"})`;
    }
    case "canonical_schema_field_soft_deleted":
    case "canonical_schema_field_restored": {
      const fieldName = typeof p.field_name === "string" ? p.field_name : "";
      const fieldId = typeof p.field_id === "string" ? p.field_id : "";
      return `${fieldName} (${fieldId})`;
    }
    default:
      return event.event_type;
  }
}

function EventRow({ event }: { event: AuditEventListItem }) {
  const [open, setOpen] = useState(false);
  const isEdit = event.event_type === "canonical_schema_edit";
  const classification =
    typeof event.payload.classification === "string"
      ? event.payload.classification
      : null;
  const changes = isEdit
    ? ((event.payload.changes ?? {}) as Record<
        string,
        { before: unknown; after: unknown }
      >)
    : null;
  return (
    <li className="flex flex-col gap-2 rounded-md border border-border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={EVENT_TONE[event.event_type] ?? "grey"}>
          {EVENT_LABEL[event.event_type] ?? event.event_type}
        </Chip>
        {classification ? (
          <Chip tone={CLASSIFICATION_TONE[classification] ?? "grey"}>
            {classification}
          </Chip>
        ) : null}
        <span className="ml-auto text-caption text-foreground-muted">
          <span title={formatAbsolute(event.occurred_at)}>
            {formatDistanceToNow(new Date(event.occurred_at), {
              addSuffix: true,
            })}
          </span>
        </span>
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-body-strong text-foreground">
          {eventSummary(event)}
        </span>
        <span className="text-caption text-foreground-muted">
          by {event.user_name}
        </span>
      </div>
      {isEdit && changes && Object.keys(changes).length > 0 ? (
        <div className="flex flex-col gap-1">
          <button
            type="button"
            onClick={() => setOpen((p) => !p)}
            className="inline-flex w-fit items-center gap-1 text-caption text-foreground-muted hover:text-foreground"
            aria-expanded={open}
          >
            {open ? (
              <ChevronDown className="h-3 w-3" aria-hidden="true" />
            ) : (
              <ChevronRight className="h-3 w-3" aria-hidden="true" />
            )}
            {open ? "Hide" : "Show"} diff
          </button>
          {open ? (
            <dl className="grid grid-cols-1 gap-2 rounded-md border border-border bg-card/30 p-3">
              {Object.entries(changes).map(([key, diff]) => (
                <div key={key} className="flex flex-col gap-1">
                  <dt className="text-label text-foreground-muted">{key}</dt>
                  <dd className="flex flex-col gap-0.5">
                    <span className="font-mono text-caption text-foreground-muted">
                      <span className="mr-1">−</span>
                      {JSON.stringify(diff.before)}
                    </span>
                    <span className="font-mono text-caption">
                      <span className="mr-1">+</span>
                      {JSON.stringify(diff.after)}
                    </span>
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

export function AuditPanel({ domainId }: { domainId: string }) {
  const query = useAuditEvents({
    domain_id: domainId,
    event_types: CANONICAL_EVENT_TYPES,
    limit: 50,
  });

  if (query.isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton variant="card" className="h-24 w-full" />
        <Skeleton variant="card" className="h-24 w-full" />
      </div>
    );
  }
  if (query.error) {
    return <ErrorInline message="Could not load audit events." />;
  }
  const items = query.data?.items ?? [];
  if (items.length === 0) {
    return (
      <EmptyState
        title="No audit events yet"
        body="Field edits, additions, deletions, and version bumps will appear here."
      />
    );
  }
  return (
    <ol className="flex flex-col gap-3">
      {items.map((event) => (
        <EventRow key={event.id} event={event} />
      ))}
    </ol>
  );
}
