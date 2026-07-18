"use client";

import { useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { Skeleton } from "@/components/shared/Skeleton";
import { TemplateKindChip } from "@/components/dis/chips/TemplateKindChip";
import { TemplateVisibilityChip } from "@/components/dis/chips/TemplateVisibilityChip";
import { useTemplates } from "@/lib/dis/hooks/use-templates";
import type { Template, TemplateDomain, TemplateListParams } from "@/types/dis";

// Phase 5c.5a → 5c.5b: templates fleet table. Row click pushes to
// /dis/templates/[id] (added in 5c.5b). context kept as a future-
// proofing slot consistent with AlertRulesTable; v1 only renders
// "fleet" content.

type Context = "fleet";

type Props = {
  context: Context;
  params?: TemplateListParams;
  emptyState?: { title: string; body?: string };
};

const DOMAIN_LABEL: Record<TemplateDomain, string> = {
  sales: "Sales",
  inventory: "Inventory",
  customers: "Customers",
  suppliers: "Suppliers",
  stores: "Stores",
  products: "Products",
};

export function TemplatesTable({ context, params, emptyState }: Props) {
  const finalParams: TemplateListParams = {
    ...(params ?? {}),
    limit: params?.limit ?? 50,
  };
  const query = useTemplates(finalParams);

  if (query.isLoading) return <Skeleton variant="row" count={5} />;
  if (query.error) {
    return (
      <ErrorInline
        message="Could not load templates."
        onRetry={() => query.refetch()}
      />
    );
  }
  const items = query.data?.items ?? [];
  if (items.length === 0) return <TemplatesEmptyState context={context} override={emptyState} />;
  return <TemplatesTableInner templates={items} />;
}

function TemplatesTableInner({ templates }: { templates: Template[] }) {
  const router = useRouter();
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="px-3 text-label text-muted-foreground">Visibility</TableHead>
          <TableHead className="text-label text-muted-foreground">Template</TableHead>
          <TableHead className="text-label text-muted-foreground">Domain</TableHead>
          <TableHead className="text-label text-muted-foreground">Tenant</TableHead>
          <TableHead className="text-label text-muted-foreground">Created by</TableHead>
          <TableHead className="text-label text-muted-foreground">Last used</TableHead>
          <TableHead className="text-label text-muted-foreground text-right">
            Uses (30d)
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {templates.map((t) => (
          <TableRow
            key={t.id}
            onClick={() => router.push(`/dis/templates/${t.id}`)}
            className="cursor-pointer"
          >
            <TableCell className="px-3 py-3">
              <div className="flex flex-wrap items-center gap-1.5">
                <TemplateVisibilityChip visibility={t.visibility} />
                {t.kind === "SUPER" ? <TemplateKindChip /> : null}
              </div>
            </TableCell>
            <TableCell>
              <div className="flex min-w-0 flex-col gap-1">
                <span className="truncate text-sm font-medium" title={t.name}>
                  {t.name}
                </span>
                <span className="font-mono text-xs text-muted-foreground">{t.id}</span>
              </div>
            </TableCell>
            <TableCell>
              <span
                className="text-sm"
                title={t.domains.map((d) => DOMAIN_LABEL[d]).join(", ")}
              >
                {t.domains.length === 1
                  ? DOMAIN_LABEL[t.domains[0]!]
                  : `Multi-domain (${t.domains.length})`}
              </span>
            </TableCell>
            <TableCell>
              <span className="text-sm">{t.tenant_name}</span>
            </TableCell>
            <TableCell>
              <span className="text-sm">{t.created_by_user_name}</span>
            </TableCell>
            <TableCell>
              <span className="text-xs text-muted-foreground">
                {t.last_used_at
                  ? formatDistanceToNow(new Date(t.last_used_at), { addSuffix: true })
                  : "—"}
              </span>
            </TableCell>
            <TableCell className="text-right">
              <span
                className={
                  t.usage_count_30d > 0
                    ? "text-sm font-medium"
                    : "text-sm text-muted-foreground"
                }
              >
                {t.usage_count_30d}
              </span>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function TemplatesEmptyState({
  context,
  override,
}: {
  context: Context;
  override?: { title: string; body?: string };
}) {
  void context;
  const title = override?.title ?? "No templates match these filters";
  const body = override?.body ?? "Try widening the domain or visibility filter.";
  return (
    <div className="flex flex-col items-center gap-3 rounded-md border border-dashed border-border px-6 py-10 text-center">
      <h3 className="text-sm font-medium">{title}</h3>
      <p className="text-caption text-muted-foreground">{body}</p>
    </div>
  );
}
