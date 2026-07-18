"use client";

import { use } from "react";
import { formatDistanceToNow } from "date-fns";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/shared/PageHeader";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { UploadStatusChip } from "@/components/dis/chips/UploadStatusChip";
import { MappingReviewView } from "@/components/dis/uploads/MappingReviewView";
import { useUpload } from "@/lib/dis/hooks/use-uploads";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function UploadDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const query = useUpload(id);

  if (query.isLoading) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Upload" />
        <section className="px-6 py-6">
          <Skeleton variant="row" count={4} />
        </section>
      </div>
    );
  }

  if (query.error) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Upload" />
        <section className="px-6 py-6">
          <ErrorInline message="Could not load upload." onRetry={() => query.refetch()} />
        </section>
      </div>
    );
  }

  const u = query.data;
  if (!u) return null;

  return (
    <div className="flex flex-1 flex-col">
      <PageHeader title={u.file_name} subtitle={`${u.tenant_name} · ${formatBytes(u.file_size_bytes)}`} />

      <section className="flex flex-col gap-6 px-6 py-6">
        <Link
          href="/dis/uploads"
          className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to uploads
        </Link>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Metadata label="Status" value={<UploadStatusChip status={u.status} />} />
          <Metadata
            label="Template"
            value={
              u.template_name ? (
                <span className="text-sm">{u.template_name}</span>
              ) : (
                <span className="text-sm text-muted-foreground">Ad-hoc</span>
              )
            }
          />
          <Metadata
            label="Rows ingested"
            value={
              u.rows_ingested === null ? (
                <span className="text-sm text-muted-foreground">—</span>
              ) : (
                <span className="text-sm tabular-nums">{u.rows_ingested.toLocaleString()}</span>
              )
            }
          />
          <Metadata
            label="Uploaded"
            value={
              <div className="flex flex-col">
                <span className="text-sm">{u.uploaded_by_name}</span>
                <span className="text-xs text-muted-foreground">
                  {formatDistanceToNow(new Date(u.uploaded_at), { addSuffix: true })}
                </span>
              </div>
            }
          />
        </div>

        <MappingReviewView upload={u} />
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
