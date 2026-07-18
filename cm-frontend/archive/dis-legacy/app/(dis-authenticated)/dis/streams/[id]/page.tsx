"use client";

import { use } from "react";
import { formatDistanceToNow } from "date-fns";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/shared/PageHeader";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import {
  Tabs,
  TabsContent,
  TabsIndicator,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { SourceStatusChip } from "@/components/dis/chips/SourceStatusChip";
import { StreamDomainChip } from "@/components/dis/chips/StreamDomainChip";
import { StreamHealthChip } from "@/components/dis/chips/StreamHealthChip";
import { SystemKindChip } from "@/components/dis/chips/SystemKindChip";
import { RunsTable } from "@/components/dis/runs/RunsTable";
import { DriftEventsTable } from "@/components/dis/schema-drift/DriftEventsTable";
import { FreshnessDetailView } from "@/components/dis/freshness/FreshnessDetailView";
import { AlertEventsTable } from "@/components/dis/alerts/AlertEventsTable";
import { ValidationRulesTable } from "@/components/dis/validation/ValidationRulesTable";
import { StreamLifecycleActions } from "@/components/dis/streams/StreamLifecycleActions";
import { humanizeCron } from "@/lib/dis/cron";
import { useStream } from "@/lib/dis/hooks/use-streams";

// Phase 5e.4b: Stream detail page. Mirrors /dis/sources/[id] tab shape
// minus the Config tab (credentials live on the parent Source, not on
// the feed). No edit / lifecycle / reassign actions in 5e.4b — those
// land in 5e.4d with the AddStreamWizard + per-stream mutations.

export default function StreamDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const query = useStream(id);

  if (query.isLoading) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Stream" />
        <section className="px-6 py-6">
          <Skeleton variant="row" count={4} />
        </section>
      </div>
    );
  }

  if (query.error) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Stream" />
        <section className="px-6 py-6">
          <ErrorInline
            message="Could not load stream."
            onRetry={() => query.refetch()}
          />
        </section>
      </div>
    );
  }

  const s = query.data;
  if (!s) return null;

  return (
    <div className="flex flex-1 flex-col">
      <PageHeader
        title={s.name}
        subtitle={`${s.tenant_name} · ${s.source_name}`}
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
          <Metadata label="Domain" value={<StreamDomainChip domain={s.domain} />} />
          <Metadata label="System" value={<SystemKindChip type={s.system_kind} />} />
          <Metadata label="Status" value={<SourceStatusChip status={s.status} />} />
          <Metadata label="Health" value={<StreamHealthChip health={s.health} />} />
          <Metadata
            label="Last run"
            value={
              s.last_run_at ? (
                <span className="text-sm">
                  {formatDistanceToNow(new Date(s.last_run_at), { addSuffix: true })}
                </span>
              ) : (
                <span className="text-sm text-muted-foreground">Never</span>
              )
            }
          />
          <Metadata
            label="Schedule"
            value={
              <div className="flex flex-col">
                <span className="text-sm">{humanizeCron(s.schedule)}</span>
                {s.schedule ? (
                  <span className="text-xs text-muted-foreground font-mono">{s.schedule}</span>
                ) : null}
              </div>
            }
          />
          <Metadata
            label="Source"
            value={
              <Link
                href={`/dis/sources/${s.source_id}`}
                className="text-sm text-primary hover:underline"
              >
                {s.source_name}
              </Link>
            }
          />
          <Metadata
            label="Created"
            value={
              <span className="text-sm">
                {formatDistanceToNow(new Date(s.created_at), { addSuffix: true })}
              </span>
            }
          />
        </div>

        <StreamLifecycleActions stream={s} />

        <Tabs defaultValue="runs">
          <TabsList>
            <TabsIndicator />
            <TabsTrigger value="runs">Runs</TabsTrigger>
            <TabsTrigger value="validation">Validation</TabsTrigger>
            <TabsTrigger value="drift">Schema drift</TabsTrigger>
            <TabsTrigger value="freshness">Freshness</TabsTrigger>
            <TabsTrigger value="alerts">Alerts</TabsTrigger>
          </TabsList>
          <TabsContent value="runs" className="mt-4">
            <RunsTable context="stream" streamId={s.id} />
          </TabsContent>
          <TabsContent value="validation" className="mt-4">
            <ValidationRulesTable context="stream" streamId={s.id} />
          </TabsContent>
          <TabsContent value="drift" className="mt-4">
            <DriftEventsTable context="stream" streamId={s.id} />
          </TabsContent>
          <TabsContent value="freshness" className="mt-4">
            <FreshnessDetailView streamId={s.id} />
          </TabsContent>
          <TabsContent value="alerts" className="mt-4">
            <AlertEventsTable context="stream" streamId={s.id} />
          </TabsContent>
        </Tabs>
      </section>
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
