"use client";

import { use } from "react";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/shared/PageHeader";
import { SourceEditForm } from "@/components/dis/sources/SourceEditForm";

export default function EditSourcePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <div className="flex flex-1 flex-col">
      <PageHeader
        title="Edit source"
        subtitle="Type and org-node assignment are immutable. Other fields can be updated."
      />
      <section className="flex flex-col gap-6 px-6 py-6">
        <Link
          href={`/dis/sources/${id}`}
          className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to source
        </Link>
        <SourceEditForm sourceId={id} />
      </section>
    </div>
  );
}
