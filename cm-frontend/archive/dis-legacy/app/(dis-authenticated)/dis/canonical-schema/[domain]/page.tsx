"use client";

import { Suspense, use, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Edit, GitBranch, Plus } from "lucide-react";
import { format } from "date-fns";

import { PageHeader } from "@/components/shared/PageHeader";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tabs,
  TabsIndicator,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { CanonicalFieldTypeChip } from "@/components/dis/chips/CanonicalFieldTypeChip";
import { EditFieldDrawer } from "@/components/dis/admin/EditFieldDrawer";
import { BumpVersionModal } from "@/components/dis/admin/BumpVersionModal";
import { AuditPanel } from "@/components/dis/admin/AuditPanel";
import {
  RestoreFieldButton,
  SoftDeleteFieldButton,
} from "@/components/dis/admin/SoftDeleteFieldButton";
import { useCanonicalDomain } from "@/lib/dis/hooks/use-canonical-schema";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { cn } from "@/lib/utils";
import type {
  CanonicalSchemaDomain,
  CanonicalSchemaField,
} from "@/types/dis";

// Phase 5e.2: consolidated canonical-schema domain page. Single route
// /dis/canonical-schema/[domain] serves both personas; PLATFORM sees
// edit affordances (Add field / Bump version / per-row Edit + Soft-
// delete) and Fields/History tab control. Tenant sees the read-only
// fields table — no tabs, no admin buttons. Old /dis/admin/canonical-
// schema/* routes deleted.

type DrawerState =
  | { kind: "closed" }
  | { kind: "add" }
  | { kind: "edit"; field: CanonicalSchemaField };

type TabValue = "fields" | "history";

function isTab(v: string | null): v is TabValue {
  return v === "fields" || v === "history";
}

function CanonicalDomainPageInner({ domainId }: { domainId: string }) {
  const snapshot = useAuthSnapshot();
  const isPlatform = snapshot?.user.userType === "PLATFORM";
  const router = useRouter();
  const searchParams = useSearchParams();
  // tab + show_deleted are admin-only state — tenants are hard-wired
  // to "fields" + false regardless of URL params.
  const tab: TabValue =
    isPlatform && isTab(searchParams.get("tab"))
      ? (searchParams.get("tab") as TabValue)
      : "fields";
  const showDeleted = isPlatform && searchParams.get("show_deleted") === "1";
  const query = useCanonicalDomain(domainId);
  const [drawer, setDrawer] = useState<DrawerState>({ kind: "closed" });
  const [bumpOpen, setBumpOpen] = useState(false);

  function changeTab(next: TabValue) {
    const sp = new URLSearchParams(searchParams.toString());
    if (next === "fields") sp.delete("tab");
    else sp.set("tab", next);
    const qs = sp.toString();
    router.replace(`/dis/canonical-schema/${domainId}${qs ? `?${qs}` : ""}`);
  }

  function toggleShowDeleted() {
    const sp = new URLSearchParams(searchParams.toString());
    if (showDeleted) sp.delete("show_deleted");
    else sp.set("show_deleted", "1");
    const qs = sp.toString();
    router.replace(`/dis/canonical-schema/${domainId}${qs ? `?${qs}` : ""}`);
  }

  const visibleFields = useMemo<CanonicalSchemaField[]>(() => {
    if (!query.data) return [];
    // Tenants always hide deleted; PLATFORM respects the show_deleted
    // toggle.
    if (isPlatform && showDeleted) return query.data.fields;
    return query.data.fields.filter((f) => !f.deleted_at);
  }, [query.data, isPlatform, showDeleted]);

  if (query.isLoading) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Canonical domain" />
        <section className="px-6 py-6">
          <Skeleton variant="row" count={4} />
        </section>
      </div>
    );
  }

  if (query.error || !query.data) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Canonical domain" />
        <section className="flex flex-col gap-4 px-6 py-6">
          <ErrorInline message="Could not load domain." />
          <BackLink />
        </section>
      </div>
    );
  }

  const domain = query.data;
  const existingFieldIds = domain.fields.map((f) => f.id);
  const deletedCount = domain.fields.filter((f) => f.deleted_at).length;

  return (
    <div className="flex flex-1 flex-col">
      <PageHeader title={domain.name} subtitle="Canonical domain" />
      <section className="flex flex-col gap-6 px-6 py-6">
        <div className="flex items-center justify-between gap-3">
          <BackLink />
          {isPlatform && tab === "fields" ? (
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setBumpOpen(true)}
              >
                <GitBranch className="h-3.5 w-3.5" />
                Bump version
              </Button>
              <Button size="sm" onClick={() => setDrawer({ kind: "add" })}>
                <Plus className="h-3.5 w-3.5" />
                Add field
              </Button>
            </div>
          ) : null}
        </div>

        {isPlatform ? (
          <Tabs
            value={tab}
            onValueChange={(v) => changeTab((v ?? "fields") as TabValue)}
          >
            <TabsList>
              <TabsIndicator />
              <TabsTrigger value="fields">Fields</TabsTrigger>
              <TabsTrigger value="history">History</TabsTrigger>
            </TabsList>
          </Tabs>
        ) : null}

        {tab === "fields" ? (
          <>
            <DomainHeader domain={domain} />
            {isPlatform && deletedCount > 0 ? (
              <label className="inline-flex w-fit items-center gap-2 text-caption text-foreground-muted">
                <input
                  type="checkbox"
                  checked={showDeleted}
                  onChange={toggleShowDeleted}
                  aria-label="Show deleted fields"
                />
                Show deleted ({deletedCount})
              </label>
            ) : null}
            <FieldsSection
              domainId={domainId}
              fields={visibleFields}
              isPlatform={isPlatform}
              onEdit={(f) => setDrawer({ kind: "edit", field: f })}
            />
          </>
        ) : (
          <AuditPanel domainId={domainId} />
        )}
      </section>

      {drawer.kind === "edit" ? (
        <EditFieldDrawer
          mode="edit"
          open={true}
          onOpenChange={(open) => {
            if (!open) setDrawer({ kind: "closed" });
          }}
          domainId={domainId}
          field={drawer.field}
        />
      ) : null}

      {drawer.kind === "add" ? (
        <EditFieldDrawer
          mode="add"
          open={true}
          onOpenChange={(open) => {
            if (!open) setDrawer({ kind: "closed" });
          }}
          domainId={domainId}
          existingFieldIds={existingFieldIds}
          onCreated={(field) => setDrawer({ kind: "edit", field })}
        />
      ) : null}

      {bumpOpen ? (
        <BumpVersionModal
          open={bumpOpen}
          onOpenChange={setBumpOpen}
          domain={domain}
        />
      ) : null}
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/dis/canonical-schema"
      className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-3.5 w-3.5" />
      Back to canonical schema
    </Link>
  );
}

function DomainHeader({ domain }: { domain: CanonicalSchemaDomain }) {
  const fieldCount = domain.field_count ?? domain.fields.length;
  return (
    <div className="flex flex-col gap-4 rounded-md border border-border bg-card/30 p-6">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-muted-foreground">{domain.id}</span>
        {domain.version ? (
          <span className="font-mono text-xs text-muted-foreground">
            · {domain.version}
          </span>
        ) : null}
      </div>
      <p className="text-sm">{domain.description}</p>
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field
          label="Fields"
          value={<span className="text-sm font-medium">{fieldCount}</span>}
        />
        {domain.version ? (
          <Field
            label="Version"
            value={<span className="text-sm">{domain.version}</span>}
          />
        ) : null}
        {domain.effective_date ? (
          <Field
            label="Effective"
            value={
              <span className="text-sm text-muted-foreground">
                {format(new Date(domain.effective_date), "MMM d, yyyy")}
              </span>
            }
          />
        ) : null}
      </dl>
    </div>
  );
}

function FieldsSection({
  domainId,
  fields,
  isPlatform,
  onEdit,
}: {
  domainId: string;
  fields: CanonicalSchemaField[];
  isPlatform: boolean;
  onEdit: (field: CanonicalSchemaField) => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-heading">Fields</h2>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="px-3 text-label text-muted-foreground">
              Type
            </TableHead>
            <TableHead className="text-label text-muted-foreground">Field</TableHead>
            <TableHead className="text-label text-muted-foreground">
              Constraints
            </TableHead>
            <TableHead className="text-label text-muted-foreground">Owner</TableHead>
            <TableHead className="text-label text-muted-foreground text-right">
              Referenced by
            </TableHead>
            {isPlatform ? <TableHead /> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {fields.map((f) => (
            <FieldRow
              key={f.id}
              domainId={domainId}
              field={f}
              isPlatform={isPlatform}
              onEdit={() => onEdit(f)}
            />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function FieldRow({
  domainId,
  field,
  isPlatform,
  onEdit,
}: {
  domainId: string;
  field: CanonicalSchemaField;
  isPlatform: boolean;
  onEdit: () => void;
}) {
  const router = useRouter();
  const refCount = field.referenced_by ?? 0;
  const isDeleted = !!field.deleted_at;
  return (
    <TableRow
      onClick={() =>
        router.push(`/dis/canonical-schema/${domainId}/${field.id}`)
      }
      className={cn("cursor-pointer", isDeleted && "opacity-60")}
    >
      <TableCell className="px-3 py-3">
        <CanonicalFieldTypeChip type={field.type} />
      </TableCell>
      <TableCell>
        <div className="flex min-w-0 flex-col gap-1">
          <span className="text-sm font-medium">
            {field.display_name ?? field.name}
            {isDeleted ? (
              <span className="ml-2 inline-flex items-center rounded-sm bg-red-50 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-red-700 ring-1 ring-red-200 dark:bg-red-500/15 dark:text-red-300 dark:ring-red-500/30">
                Deleted
              </span>
            ) : null}
          </span>
          <span className="font-mono text-xs text-muted-foreground">{field.id}</span>
          <span
            className="truncate text-caption text-muted-foreground"
            title={field.description}
          >
            {field.description}
          </span>
        </div>
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap items-center gap-1">
          {field.required ? <Badge tone="required">required</Badge> : null}
          {field.nullable ? <Badge tone="muted">nullable</Badge> : null}
          {field.unique ? <Badge tone="info">unique</Badge> : null}
          {field.pii ? <Badge tone="warning">PII</Badge> : null}
        </div>
      </TableCell>
      <TableCell>
        <span className="text-sm">{field.business_owner ?? "—"}</span>
      </TableCell>
      <TableCell className="text-right">
        <span
          className={
            refCount > 0 ? "text-sm font-medium" : "text-sm text-muted-foreground"
          }
        >
          {refCount}
        </span>
      </TableCell>
      {isPlatform ? (
        // stopPropagation on the cell so action-button clicks don't
        // also trigger the row's entity-detail navigation.
        <TableCell
          className="text-right"
          onClick={(e) => e.stopPropagation()}
        >
          {isDeleted ? (
            <RestoreFieldButton field={field} domainId={domainId} />
          ) : (
            <div className="inline-flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={onEdit}
                aria-label={`Edit ${field.display_name ?? field.name}`}
              >
                <Edit className="h-3.5 w-3.5" />
                Edit
              </Button>
              <SoftDeleteFieldButton field={field} domainId={domainId} />
            </div>
          )}
        </TableCell>
      ) : null}
    </TableRow>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-label text-muted-foreground">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

// Compact constraint badges for the fields table. Smaller / denser
// than the shared Chip primitive to fit inside a table cell.
function Badge({
  tone,
  children,
}: {
  tone: "required" | "muted" | "info" | "warning";
  children: React.ReactNode;
}) {
  const cls = {
    required:
      "bg-zinc-100 text-zinc-800 ring-zinc-300 dark:bg-zinc-500/15 dark:text-zinc-200 dark:ring-zinc-500/30",
    muted:
      "bg-zinc-50 text-zinc-600 ring-zinc-200 dark:bg-zinc-500/10 dark:text-zinc-400 dark:ring-zinc-500/20",
    info: "bg-blue-50 text-blue-700 ring-blue-200 dark:bg-blue-500/15 dark:text-blue-300 dark:ring-blue-500/30",
    warning:
      "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-500/15 dark:text-amber-300 dark:ring-amber-500/30",
  }[tone];
  return (
    <span
      className={`inline-flex items-center rounded-sm px-1.5 py-0.5 text-micro ring-1 ring-inset ${cls}`}
    >
      {children}
    </span>
  );
}

export default function CanonicalDomainDetailPage({
  params,
}: {
  params: Promise<{ domain: string }>;
}) {
  const { domain: domainId } = use(params);
  return (
    <Suspense fallback={null}>
      <CanonicalDomainPageInner domainId={domainId} />
    </Suspense>
  );
}
