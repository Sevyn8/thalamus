"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/shared/PageHeader";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { CanonicalFieldTypeChip } from "@/components/dis/chips/CanonicalFieldTypeChip";
import { useCanonicalField } from "@/lib/dis/hooks/use-canonical-schema";
import type { CanonicalSchemaDomain, CanonicalSchemaField } from "@/types/dis";

// Phase 5c.7b: canonical-field detail. Header card with field
// metadata + type chip + constraint badges + business owner +
// referenced_by + example_values + constraints list. Read-only —
// schema-edit affordances live inline on /dis/canonical-schema/
// [domain] (Phase 5e.2 consolidated route).
//
// Route param is [entity] (5c.7a ambiguity viii — kept the existing
// dynamic-route directory name to avoid build-tracked path drift).
// Treated as field_id semantically.

export default function CanonicalFieldDetailPage({
  params,
}: {
  params: Promise<{ domain: string; entity: string }>;
}) {
  const { domain: domainId, entity: fieldId } = use(params);
  const query = useCanonicalField(domainId, fieldId);

  if (query.isLoading) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Canonical field" />
        <section className="px-6 py-6">
          <Skeleton variant="row" count={4} />
        </section>
      </div>
    );
  }

  if (query.error || !query.domain || !query.field) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Canonical field" />
        <section className="flex flex-col gap-4 px-6 py-6">
          <ErrorInline message="Could not load canonical field." />
          <BackLink domainId={domainId} domainName={query.domain?.name ?? null} />
        </section>
      </div>
    );
  }

  const { domain, field } = query;

  return (
    <div className="flex flex-1 flex-col">
      <PageHeader
        title={field.display_name ?? field.name}
        subtitle={`${domain.name} · canonical field`}
      />
      <section className="flex flex-col gap-6 px-6 py-6">
        <BackLink domainId={domain.id} domainName={domain.name} />
        <Header domain={domain} field={field} />
        {field.example_values && field.example_values.length > 0 ? (
          <ExampleValues values={field.example_values} />
        ) : null}
        {field.constraints && field.constraints.length > 0 ? (
          <ConstraintsList constraints={field.constraints} />
        ) : null}
        <UsageSummary field={field} />
      </section>
    </div>
  );
}

function BackLink({
  domainId,
  domainName,
}: {
  domainId: string;
  domainName: string | null;
}) {
  return (
    <Link
      href={`/dis/canonical-schema/${domainId}`}
      className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-3.5 w-3.5" />
      Back to {domainName ?? "domain"}
    </Link>
  );
}

function Header({
  domain,
  field,
}: {
  domain: CanonicalSchemaDomain;
  field: CanonicalSchemaField;
}) {
  return (
    <div className="flex flex-col gap-4 rounded-md border border-border bg-card/30 p-6">
      <div className="flex flex-wrap items-center gap-2">
        <CanonicalFieldTypeChip type={field.type} />
        {field.required ? <Badge tone="required">required</Badge> : null}
        {field.nullable ? <Badge tone="muted">nullable</Badge> : null}
        {field.unique ? <Badge tone="info">unique</Badge> : null}
        {field.pii ? <Badge tone="warning">PII</Badge> : null}
        <span className="font-mono text-xs text-muted-foreground">{field.id}</span>
      </div>
      <p className="text-sm">{field.description}</p>
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field
          label="Domain"
          value={
            <Link
              href={`/dis/canonical-schema/${domain.id}`}
              className="text-sm text-primary hover:underline"
            >
              {domain.name}
            </Link>
          }
        />
        <Field
          label="Type"
          value={<span className="text-sm">{field.type}</span>}
        />
        {field.business_owner ? (
          <Field
            label="Business owner"
            value={<span className="text-sm">{field.business_owner}</span>}
          />
        ) : null}
        {field.synonyms.length > 0 ? (
          <Field
            label="Synonyms"
            value={
              <span className="font-mono text-caption text-muted-foreground">
                {field.synonyms.join(", ")}
              </span>
            }
            wide
          />
        ) : null}
      </dl>
    </div>
  );
}

function ExampleValues({ values }: { values: string[] }) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-heading">Example values</h2>
      <ul className="flex flex-wrap gap-2">
        {values.map((v) => (
          <li
            key={v}
            className="rounded-sm border border-border bg-card/20 px-2 py-1 font-mono text-xs"
          >
            {v}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ConstraintsList({ constraints }: { constraints: string[] }) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-heading">Constraints</h2>
      <ul className="flex flex-col gap-1.5 rounded-md border border-border bg-card/20 px-4 py-3">
        {constraints.map((c) => (
          <li key={c} className="text-sm">
            · {c}
          </li>
        ))}
      </ul>
    </div>
  );
}

function UsageSummary({ field }: { field: CanonicalSchemaField }) {
  const refCount = field.referenced_by ?? 0;
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-heading">Referenced by</h2>
      <div className="flex flex-col gap-1 rounded-md border border-border bg-card/20 px-4 py-3">
        <span
          className={
            refCount > 0
              ? "text-subheading font-medium"
              : "text-subheading text-muted-foreground"
          }
        >
          {refCount}
        </span>
        <span className="text-caption text-muted-foreground">
          {refCount === 0
            ? "Not yet referenced by any template, source, or validation rule."
            : `Templates, sources, and validation rules referencing this field across all tenants. Real backend will break this down by resource type; v1 surfaces the rolled-up count.`}
        </span>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  wide,
}: {
  label: string;
  value: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={wide ? "sm:col-span-3" : undefined}>
      <dt className="text-label text-muted-foreground">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

// Compact constraint badges, same shape as the domain detail page.
// Two-consumer rule: lift to a shared component if a third surface
// needs them (5c.8 admin canonical-schema-edit is a likely third).
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
