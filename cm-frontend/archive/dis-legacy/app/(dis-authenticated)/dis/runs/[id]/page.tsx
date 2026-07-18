"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/shared/PageHeader";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { RunDetailHeader } from "@/components/dis/runs/RunDetailHeader";
import { RunCounters } from "@/components/dis/runs/RunCounters";
import { RunErrorPanel } from "@/components/dis/runs/RunErrorPanel";
import { RunLogsStub } from "@/components/dis/runs/RunLogsStub";
import { useRun } from "@/lib/dis/hooks/use-runs";

// Phase 5c.3b: /dis/runs/[id]. Replaces the 5c.3a UnderConstruction
// stub. Composition: header card → counters grid → error panel
// (FAILED only) → logs stub. 404 path renders an inline error with
// a link back to /dis/runs (no auto-redirect — run detail has no
// natural redirect target since the user could've come from the
// fleet view OR the per-source Runs tab).

export default function RunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const query = useRun(id);

  if (query.isLoading) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Run" />
        <section className="px-6 py-6">
          <Skeleton variant="row" count={5} />
        </section>
      </div>
    );
  }

  if (query.error || !query.data) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Run" />
        <section className="flex flex-col gap-4 px-6 py-6">
          <ErrorInline
            message="Could not load run."
            onRetry={() => query.refetch()}
          />
          <Link
            href="/dis/runs"
            className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to runs
          </Link>
        </section>
      </div>
    );
  }

  const run = query.data;
  return (
    <div className="flex flex-1 flex-col">
      <PageHeader title="Run detail" subtitle={run.source_name} />
      <section className="flex flex-col gap-6 px-6 py-6">
        <Link
          href="/dis/runs"
          className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to runs
        </Link>
        <RunDetailHeader run={run} />
        <RunCounters run={run} />
        {run.status === "FAILED" ? <RunErrorPanel run={run} /> : null}
        <RunLogsStub run={run} />
      </section>
    </div>
  );
}
