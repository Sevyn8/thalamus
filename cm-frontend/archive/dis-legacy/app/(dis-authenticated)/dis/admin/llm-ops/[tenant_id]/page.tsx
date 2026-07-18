"use client";

import { use, useMemo } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, ShieldAlert } from "lucide-react";

import { PageHeader } from "@/components/shared/PageHeader";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import {
  Tabs,
  TabsIndicator,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useLlmOpsTenant } from "@/lib/dis/hooks/use-llm-ops";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { formatCost } from "@/lib/dis/format";
import type { LlmOpsTimeWindow } from "@/types/dis";

// Phase 5c.8c: per-tenant LLM ops detail. Same window-param wiring
// as the fleet page so navigation preserves the user's window
// selection. Detail surfaces two stacked sections:
//   1. Per-model breakdown table (sorted by total_cost_usd desc)
//   2. Recent failures list (last 10 across all models, occurred_at desc)
//
// Demo narrative: Anjali clicks Buc-ee's from the fleet, sees
// Gemini 1.5 flash dominant with column_mapping bulk; below, ~5
// recent failures mixing RATE_LIMIT_EXCEEDED and TIMEOUT.

const WINDOW_OPTIONS: { value: LlmOpsTimeWindow; label: string }[] = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
];

function parseWindow(value: string | null): LlmOpsTimeWindow {
  if (value === "24h" || value === "7d" || value === "30d") return value;
  return "30d";
}

function humanizeTokens(n: number): string {
  if (n < 1000) return n.toLocaleString();
  if (n < 1_000_000) {
    const v = (n / 1000).toFixed(1).replace(/\.0$/, "");
    return `${v}K`;
  }
  const v = (n / 1_000_000).toFixed(1).replace(/\.0$/, "");
  return `${v}M`;
}

const REQUEST_TYPE_LABELS: Record<string, string> = {
  column_mapping: "Column mapping",
  synonym_discovery: "Synonym discovery",
  validator_synthesis: "Validator synthesis",
};

export default function LlmOpsTenantDetailPage({
  params,
}: {
  params: Promise<{ tenant_id: string }>;
}) {
  const { tenant_id: tenantId } = use(params);
  const snapshot = useAuthSnapshot();
  const isPlatform = snapshot?.user.userType === "PLATFORM";
  const router = useRouter();
  const searchParams = useSearchParams();
  const window = useMemo(
    () => parseWindow(searchParams.get("window")),
    [searchParams],
  );
  const query = useLlmOpsTenant(tenantId, window);

  function setWindow(next: string): void {
    const params = new URLSearchParams(searchParams.toString());
    params.set("window", next);
    router.replace(`/dis/admin/llm-ops/${tenantId}?${params.toString()}`);
  }

  if (!isPlatform) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="LLM operations" subtitle="Admin only" />
        <section className="flex flex-col items-center gap-3 rounded-md border border-dashed border-border px-6 py-10 mx-6 my-6 text-center">
          <ShieldAlert className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
          <h3 className="text-sm font-medium">Admin only</h3>
          <p className="text-caption text-muted-foreground max-w-md">
            LLM ops requires platform access.
          </p>
        </section>
      </div>
    );
  }

  if (query.isLoading) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="LLM operations" />
        <section className="px-6 py-6">
          <Skeleton variant="row" count={6} />
        </section>
      </div>
    );
  }

  if (query.error || !query.data) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="LLM operations" />
        <section className="flex flex-col gap-4 px-6 py-6">
          <ErrorInline message="Could not load tenant detail." />
          <Link
            href={`/dis/admin/llm-ops?window=${window}`}
            className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back
          </Link>
        </section>
      </div>
    );
  }

  const detail = query.data;
  const errorRatePct = detail.error_rate * 100;

  return (
    <div className="flex flex-1 flex-col">
      <PageHeader
        title={`LLM ops · ${detail.tenant_name}`}
        subtitle={`${detail.request_count.toLocaleString()} requests · ${formatCost(detail.total_cost_usd)} · ${detail.avg_latency_ms.toLocaleString()} ms avg · ${errorRatePct.toFixed(1)}% errors`}
      />
      <section className="flex flex-col gap-4 px-6 py-6">
        <div className="flex items-center justify-between gap-3">
          <Link
            href={`/dis/admin/llm-ops?window=${window}`}
            className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to fleet
          </Link>
          <Tabs value={window} onValueChange={(v) => setWindow(String(v))}>
            <TabsList aria-label="Time window">
              <TabsIndicator />
              {WINDOW_OPTIONS.map((opt) => (
                <TabsTrigger key={opt.value} value={opt.value}>
                  {opt.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>

        <h2 className="text-heading">Per-model breakdown</h2>
        {detail.models.length === 0 ? (
          <div className="rounded-md border border-dashed border-border bg-muted/30 p-3 text-sm text-muted-foreground">
            No LLM activity in this window.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-label text-muted-foreground">
                  Model
                </TableHead>
                <TableHead className="text-label text-muted-foreground text-right">
                  Cost
                </TableHead>
                <TableHead className="text-label text-muted-foreground text-right">
                  Requests
                </TableHead>
                <TableHead className="text-label text-muted-foreground text-right">
                  Avg latency
                </TableHead>
                <TableHead className="text-label text-muted-foreground text-right">
                  Error rate
                </TableHead>
                <TableHead className="text-label text-muted-foreground">
                  By request type
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {detail.models.map((m) => {
                const pct = m.error_rate * 100;
                const errClass = pct > 5 ? "text-danger font-medium" : "";
                return (
                  <TableRow key={m.model}>
                    <TableCell>
                      <span className="font-mono text-sm">{m.model}</span>
                    </TableCell>
                    <TableCell className="text-right text-sm font-medium">
                      {formatCost(m.total_cost_usd)}
                    </TableCell>
                    <TableCell className="text-right text-sm">
                      {m.request_count.toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right text-sm">
                      {m.avg_latency_ms.toLocaleString()} ms
                    </TableCell>
                    <TableCell className="text-right text-sm">
                      <span className={errClass}>{pct.toFixed(1)}%</span>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {m.by_request_type
                        .map(
                          (b) =>
                            `${REQUEST_TYPE_LABELS[b.request_type] ?? b.request_type} (${b.request_count})`,
                        )
                        .join(" · ")}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}

        <h2 className="text-heading mt-2">
          Recent failures{" "}
          <span className="text-caption text-muted-foreground">
            (last 10 in window)
          </span>
        </h2>
        {detail.recent_failures.length === 0 ? (
          <div className="rounded-md border border-dashed border-border bg-muted/30 p-3 text-sm text-muted-foreground">
            No failures in this window.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-label text-muted-foreground">
                  When
                </TableHead>
                <TableHead className="text-label text-muted-foreground">
                  Model
                </TableHead>
                <TableHead className="text-label text-muted-foreground">
                  Request type
                </TableHead>
                <TableHead className="text-label text-muted-foreground">
                  Error
                </TableHead>
                <TableHead className="text-label text-muted-foreground text-right">
                  Tokens
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {detail.recent_failures.map((f) => (
                <TableRow key={f.id}>
                  <TableCell className="text-micro font-mono text-muted-foreground">
                    {new Date(f.occurred_at).toISOString().slice(0, 16).replace("T", " ")}
                  </TableCell>
                  <TableCell className="text-sm font-mono">{f.model}</TableCell>
                  <TableCell className="text-sm">
                    {REQUEST_TYPE_LABELS[f.request_type] ?? f.request_type}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-col gap-0.5">
                      <span className="text-sm font-medium text-danger">
                        {f.error_code}
                      </span>
                      <span className="text-caption text-muted-foreground">
                        {f.error_message}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-right text-sm font-mono">
                    {humanizeTokens(f.input_tokens)} /{" "}
                    {humanizeTokens(f.output_tokens)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>
    </div>
  );
}
