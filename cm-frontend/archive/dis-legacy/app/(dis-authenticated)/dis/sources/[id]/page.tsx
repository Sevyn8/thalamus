"use client";

import { use } from "react";
import { formatDistanceToNow } from "date-fns";
import { AlertTriangle, ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/shared/PageHeader";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { Button } from "@/components/ui/button";
import {
  Tabs,
  TabsContent,
  TabsIndicator,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { SourceStatusChip } from "@/components/dis/chips/SourceStatusChip";
import { SystemKindChip } from "@/components/dis/chips/SystemKindChip";
import { SourceConfigDisplay } from "@/components/dis/sources/SourceConfigDisplay";
import { SourceLifecycleActions } from "@/components/dis/sources/SourceLifecycleActions";
import { StreamsTable } from "@/components/dis/streams/StreamsTable";
import { useSource } from "@/lib/dis/hooks/use-sources";
import { useStreams } from "@/lib/dis/hooks/use-streams";

// Phase 5e.4c: Source detail narrowed to system identity. Two tabs:
// Configuration (credentials) + Streams (feeds under this source).
// Operational tabs (Runs / Validation / Drift / Freshness / Alerts)
// moved to /dis/streams/[id] since those signals are per-feed. Header
// card drops Health / Last run / Schedule tiles for the same reason.

export default function SourceDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const query = useSource(id);

  if (query.isLoading) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Source" />
        <section className="px-6 py-6">
          <Skeleton variant="row" count={4} />
        </section>
      </div>
    );
  }

  if (query.error) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Source" />
        <section className="px-6 py-6">
          <ErrorInline
            message="Could not load source."
            onRetry={() => query.refetch()}
          />
        </section>
      </div>
    );
  }

  const s = query.data;
  if (!s) return null;

  // Phase 5e.7b: ONBOARDING banner with "Continue setup" CTA retired
  // alongside ContinueOnboardingFlow. AddSourceWizard always produces
  // ACTIVE sources post-5e.4d; the 2 legacy ONBOARDING-status fixture
  // sources surface their status via the chip in the header card, no
  // completion CTA. 5e.4e cleanup will decide whether to flip them
  // to ACTIVE or leave as orphan-state demo fixtures.

  return (
    <div className="flex flex-1 flex-col">
      <PageHeader
        title={s.name}
        subtitle={`${s.tenant_name}${s.org_node_name ? ` · ${s.org_node_name}` : ""}`}
      />

      <section className="flex flex-col gap-6 px-6 py-6">
        <Link
          href="/dis/sources"
          className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to sources &amp; streams
        </Link>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Metadata label="System" value={<SystemKindChip type={s.type} />} />
          <Metadata
            label="Status"
            value={
              <div className="flex items-center gap-2 flex-wrap">
                <SourceStatusChip status={s.status} />
                {s.untested_at_creation ? (
                  <span
                    className="inline-flex items-center gap-1 rounded-md bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 ring-1 ring-inset ring-amber-300 dark:bg-amber-500/15 dark:text-amber-200 dark:ring-amber-500/40"
                    title="Untested at creation — the test step was skipped at creation or onboarding completion."
                  >
                    <AlertTriangle className="h-3 w-3" />
                    Untested
                  </span>
                ) : null}
              </div>
            }
          />
          <Metadata
            label="Streams"
            value={<span className="text-sm font-medium">{s.stream_count}</span>}
          />
          <Metadata
            label="Org node"
            value={
              s.org_node_code ? (
                <span className="text-sm font-mono">{s.org_node_code}</span>
              ) : (
                <span className="text-sm text-muted-foreground">—</span>
              )
            }
          />
          <Metadata label="Owner" value={<span className="text-sm">{s.owner_name ?? "—"}</span>} />
          <Metadata
            label="Created"
            value={
              <span className="text-sm">
                {formatDistanceToNow(new Date(s.created_at), { addSuffix: true })}
              </span>
            }
          />
        </div>

        <SourceLifecycleActions source={s} />

        <Tabs defaultValue="streams">
          <TabsList>
            <TabsIndicator />
            <TabsTrigger value="streams">Streams</TabsTrigger>
            <TabsTrigger value="config">Configuration</TabsTrigger>
          </TabsList>
          <TabsContent value="streams" className="mt-4">
            {/* Phase 5e.4c: feeds under this source. Reuses StreamsTable
                directly; row click → /dis/streams/[id]. Per-feed signal
                surfaces (Runs / Validation / Drift / Freshness / Alerts)
                live on the Stream detail page (5e.4b). */}
            <SourceStreamsTab sourceId={s.id} />
          </TabsContent>
          <TabsContent value="config" className="mt-4">
            <div className="rounded-md border border-border bg-card/30 p-4">
              <SourceConfigDisplay type={s.type} config={s.connection_config} />
            </div>
            <div className="mt-3 flex justify-end">
              <Link
                href={`/dis/sources/${s.id}/edit`}
                className="text-sm text-primary hover:underline"
              >
                Edit configuration →
              </Link>
            </div>
          </TabsContent>
        </Tabs>
      </section>
    </div>
  );
}

function SourceStreamsTab({ sourceId }: { sourceId: string }) {
  const router = useRouter();
  const query = useStreams({ source_id: sourceId });

  if (query.isLoading) return <Skeleton variant="row" count={3} />;
  if (query.error) {
    return (
      <ErrorInline
        message="Could not load streams for this source."
        onRetry={() => query.refetch()}
      />
    );
  }
  const items = query.data?.items ?? [];
  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-md border border-dashed border-border px-6 py-10 text-center">
        <h3 className="text-sm font-medium">No streams configured yet</h3>
        <p className="text-caption text-muted-foreground">
          Add the first data feed under this source — orders,
          inventory, customers, etc.
        </p>
        <Button
          render={<Link href={`/dis/streams/new?source=${sourceId}`} />}
          nativeButton={false}
        >
          + Add stream to this source
        </Button>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">
        <Button
          variant="outline"
          size="sm"
          render={<Link href={`/dis/streams/new?source=${sourceId}`} />}
          nativeButton={false}
        >
          + Add stream
        </Button>
      </div>
      <StreamsTable
        streams={items}
        onSelect={(id) => router.push(`/dis/streams/${id}`)}
      />
    </div>
  );
}

function Metadata({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-md border border-border bg-card/30 p-4">
      <span className="text-label text-muted-foreground">{label}</span>
      <div className="flex items-center">{value}</div>
    </div>
  );
}
