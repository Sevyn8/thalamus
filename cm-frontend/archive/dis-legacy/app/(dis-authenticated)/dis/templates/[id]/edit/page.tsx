"use client";

import { use, useId, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Loader2 } from "lucide-react";

import { PageHeader } from "@/components/shared/PageHeader";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/client";
import { useTemplate, useUpdateTemplate } from "@/lib/dis/hooks/use-templates";
import type { Template, TemplateVisibility } from "@/types/dis";

// Phase 5e.6: light edit — name + description + visibility only.
// Domains immutable because column_mappings derive from them and
// downstream uploads reference the template by id. Re-create rather
// than mutate when domain coverage needs to change.

export default function EditTemplatePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const query = useTemplate(id);
  const update = useUpdateTemplate(id);
  const router = useRouter();

  if (query.isLoading) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Edit template" />
        <section className="px-6 py-6">
          <Skeleton variant="row" count={4} />
        </section>
      </div>
    );
  }
  if (query.error || !query.data) {
    return (
      <div className="flex flex-1 flex-col">
        <PageHeader title="Edit template" />
        <section className="flex flex-col gap-4 px-6 py-6">
          <ErrorInline
            message="Could not load template."
            onRetry={() => query.refetch()}
          />
        </section>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col">
      <PageHeader
        title="Edit template"
        subtitle={query.data.name}
      />
      <section className="flex flex-col gap-6 px-6 py-6">
        <Link
          href={`/dis/templates/${id}`}
          className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back to template
        </Link>
        <EditBody template={query.data} update={update} router={router} />
      </section>
    </div>
  );
}

type BodyProps = {
  template: Template;
  update: ReturnType<typeof useUpdateTemplate>;
  router: ReturnType<typeof useRouter>;
};

function EditBody({ template, update, router }: BodyProps) {
  const [name, setName] = useState(template.name);
  const [description, setDescription] = useState(template.description);
  const [visibility, setVisibility] = useState<TemplateVisibility>(
    template.visibility,
  );
  const [submitError, setSubmitError] = useState<string | null>(null);
  const nameId = useId();
  const descId = useId();
  const privId = useId();
  const sharedId = useId();

  const canSave = name.trim().length > 0 && !update.isPending;

  async function onSave() {
    if (!canSave) return;
    setSubmitError(null);
    try {
      await update.mutateAsync({
        name: name.trim(),
        description: description.trim(),
        visibility,
      });
      router.push(`/dis/templates/${template.id}`);
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Save failed. Try again.");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <label htmlFor={nameId} className="text-label text-muted-foreground">
          Template name
        </label>
        <Input
          id={nameId}
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={120}
        />
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor={descId} className="text-label text-muted-foreground">
          Description
        </label>
        <textarea
          id={descId}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          maxLength={500}
          className="rounded-md border border-input bg-background px-2.5 py-2 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none dark:bg-input/30"
        />
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-label text-muted-foreground">Visibility</span>
        <div className="flex flex-col gap-2">
          <label
            htmlFor={sharedId}
            className="flex items-start gap-3 rounded-md border border-border bg-card/30 p-3 cursor-pointer hover:bg-surface-raised"
          >
            <input
              type="radio"
              id={sharedId}
              name="edit-visibility"
              value="TENANT_SHARED"
              checked={visibility === "TENANT_SHARED"}
              onChange={() => setVisibility("TENANT_SHARED")}
              className="mt-0.5"
            />
            <span className="flex flex-col gap-0.5">
              <span className="text-sm font-medium">Tenant-shared</span>
              <span className="text-caption text-muted-foreground">
                Anyone in your tenant can apply this template.
              </span>
            </span>
          </label>
          <label
            htmlFor={privId}
            className="flex items-start gap-3 rounded-md border border-border bg-card/30 p-3 cursor-pointer hover:bg-surface-raised"
          >
            <input
              type="radio"
              id={privId}
              name="edit-visibility"
              value="PRIVATE"
              checked={visibility === "PRIVATE"}
              onChange={() => setVisibility("PRIVATE")}
              className="mt-0.5"
            />
            <span className="flex flex-col gap-0.5">
              <span className="text-sm font-medium">Private</span>
              <span className="text-caption text-muted-foreground">
                Only you can apply this template.
              </span>
            </span>
          </label>
        </div>
      </div>

      <p className="text-caption text-muted-foreground">
        Domains and column mappings are immutable. To change domain
        coverage, create a new template.
      </p>

      {submitError ? <ErrorInline message={submitError} /> : null}

      <div className="flex items-center justify-between gap-3 border-t border-border pt-4">
        <Button
          variant="ghost"
          onClick={() => router.push(`/dis/templates/${template.id}`)}
        >
          Cancel
        </Button>
        <Button onClick={onSave} disabled={!canSave}>
          {update.isPending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Saving…
            </>
          ) : (
            "Save changes"
          )}
        </Button>
      </div>
    </div>
  );
}
