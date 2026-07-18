"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, Download } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

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
import { TemplateKindChip } from "@/components/dis/chips/TemplateKindChip";
import { TemplateVisibilityChip } from "@/components/dis/chips/TemplateVisibilityChip";
import { useTemplate } from "@/lib/dis/hooks/use-templates";
import { downloadTemplateCsv } from "@/lib/dis/templates/csv-export";
import type { Template, TemplateDomain } from "@/types/dis";

// Phase 5c.5b: template detail. Header card with metadata + column-
// mappings table. Read-only — capture (save-mapping-as-template) +
// edit defer to a later chunk alongside apply-template integrations
// on uploads/sources.

const DOMAIN_LABEL: Record<TemplateDomain, string> = {
  sales: "Sales",
  inventory: "Inventory",
  customers: "Customers",
  suppliers: "Suppliers",
  stores: "Stores",
  products: "Products",
};

export default function TemplateDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const query = useTemplate(id);

  if (query.isLoading) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Template" />
        <section className="px-6 py-6">
          <Skeleton variant="row" count={4} />
        </section>
      </div>
    );
  }

  if (query.error || !query.data) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Template" />
        <section className="flex flex-col gap-4 px-6 py-6">
          <ErrorInline message="Could not load template." onRetry={() => query.refetch()} />
          <BackLink />
        </section>
      </div>
    );
  }

  const template = query.data;

  return (
    <div className="flex flex-1 flex-col">
      <PageHeader
        title={template.name}
        subtitle={template.tenant_name}
        rightSlot={
          <Button
            variant="outline"
            onClick={() => downloadTemplateCsv(template)}
          >
            <Download className="h-4 w-4" aria-hidden="true" />
            Download CSV
          </Button>
        }
      />
      <section className="flex flex-col gap-6 px-6 py-6">
        <BackLink />
        <Header template={template} />
        <Mappings template={template} />
      </section>
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/dis/templates"
      className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-3.5 w-3.5" />
      Back to templates
    </Link>
  );
}

function Header({ template }: { template: Template }) {
  return (
    <div className="flex flex-col gap-4 rounded-md border border-border bg-card/30 p-6">
      <div className="flex flex-wrap items-center gap-2">
        <TemplateVisibilityChip visibility={template.visibility} />
        {template.kind === "SUPER" ? <TemplateKindChip /> : null}
        <span
          className="text-sm text-muted-foreground"
          title={template.domains.map((d) => DOMAIN_LABEL[d]).join(", ")}
        >
          {template.domains.length === 1
            ? DOMAIN_LABEL[template.domains[0]!]
            : template.domains.map((d) => DOMAIN_LABEL[d]).join(" · ")}
        </span>
        <span className="font-mono text-xs text-muted-foreground">{template.id}</span>
      </div>
      {template.description ? (
        <p className="text-sm">{template.description}</p>
      ) : null}
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Field
          label="Created by"
          value={<span className="text-sm">{template.created_by_user_name}</span>}
        />
        <Field
          label="Created"
          value={
            <span className="text-sm text-muted-foreground">
              {formatDistanceToNow(new Date(template.created_at), { addSuffix: true })}
            </span>
          }
        />
        <Field
          label="Last used"
          value={
            <span className="text-sm text-muted-foreground">
              {template.last_used_at
                ? formatDistanceToNow(new Date(template.last_used_at), {
                    addSuffix: true,
                  })
                : "Never used"}
            </span>
          }
        />
        <Field
          label="Uses (30d)"
          value={
            <span
              className={
                template.usage_count_30d > 0
                  ? "text-sm font-medium"
                  : "text-sm text-muted-foreground"
              }
            >
              {template.usage_count_30d}
            </span>
          }
        />
        <Field
          label="Mappings"
          value={<span className="text-sm">{template.column_mappings.length}</span>}
        />
      </dl>
    </div>
  );
}

function Mappings({ template }: { template: Template }) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-heading">Column mappings</h2>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="px-3 text-label text-muted-foreground">
              Source column
            </TableHead>
            <TableHead className="text-label text-muted-foreground">
              Canonical field
            </TableHead>
            <TableHead className="text-label text-muted-foreground">
              Transformation
            </TableHead>
            <TableHead className="text-label text-muted-foreground">PII</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {template.column_mappings.map((m) => (
            <TableRow key={m.source_column}>
              <TableCell className="px-3 py-3">
                <span className="font-mono text-sm">{m.source_column}</span>
              </TableCell>
              <TableCell>
                {/* Phase 5c.7b cross-link: canonical_field_id maps
                    to /dis/canonical-schema/{domain}/{field_id} where
                    domain is the prefix before the first dot. */}
                <Link
                  href={`/dis/canonical-schema/${m.canonical_field_id.split(".")[0]}/${m.canonical_field_id}`}
                  className="flex min-w-0 flex-col gap-0.5 hover:underline"
                >
                  <span className="text-sm text-primary">
                    {m.canonical_field_label}
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {m.canonical_field_id}
                  </span>
                </Link>
              </TableCell>
              <TableCell>
                {m.transformation ? (
                  <span className="font-mono text-xs text-muted-foreground">
                    {m.transformation}
                  </span>
                ) : (
                  <span className="text-xs text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell>
                {m.redact_pii ? (
                  <span className="text-xs font-medium text-warning">Redacted</span>
                ) : (
                  <span className="text-xs text-muted-foreground">—</span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
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
