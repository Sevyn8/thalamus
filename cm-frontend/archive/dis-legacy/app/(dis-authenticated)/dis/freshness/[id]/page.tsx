"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, ExternalLink } from "lucide-react";

import { PageHeader } from "@/components/shared/PageHeader";
import { FreshnessDetailView } from "@/components/dis/freshness/FreshnessDetailView";
import { useFreshnessForStream } from "@/lib/dis/hooks/use-freshness";

// Phase 5e.4b: /dis/freshness/[id] route id now resolves as a
// stream_id (freshness is 1:1 with Stream post-Source/Stream split).
// Multi-SLO sources like Buc-ee's Shopify (orders + inventory) get
// distinct routes per feed. The page subtitle reads stream name; the
// cross-link goes to the Stream detail page (whose Source line cross-
// references back up to the parent system).

export default function FreshnessDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: streamId } = use(params);
  const query = useFreshnessForStream(streamId);
  const streamName = query.data?.stream_name;

  return (
    <div className="flex flex-1 flex-col">
      <PageHeader
        title="Freshness"
        subtitle={streamName ?? undefined}
      />
      <section className="flex flex-col gap-6 px-6 py-6">
        <div className="flex items-center justify-between">
          <Link
            href="/dis/freshness"
            className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to freshness
          </Link>
          {query.data ? (
            <Link
              href={`/dis/streams/${query.data.stream_id}`}
              className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
            >
              Open stream
              <ExternalLink className="h-3 w-3" />
            </Link>
          ) : null}
        </div>
        <FreshnessDetailView streamId={streamId} />
      </section>
    </div>
  );
}
