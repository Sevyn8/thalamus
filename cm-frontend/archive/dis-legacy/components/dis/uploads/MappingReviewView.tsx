"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Sparkles, Pencil, ExternalLink } from "lucide-react";

import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { ApiError } from "@/lib/api/client";
import { useCanonicalSchema } from "@/lib/dis/hooks/use-canonical-schema";
import { useDisSettings } from "@/lib/dis/hooks/use-dis-settings";
import { useConfirmMapping } from "@/lib/dis/hooks/use-uploads";
import type { UploadDetail } from "@/types/dis";

import { ColumnMappingRow } from "./ColumnMappingRow";
import { MappingActions } from "./MappingActions";
import { SampleRowsTable } from "./SampleRowsTable";

type Props = {
  upload: UploadDetail;
};

// Top-level mapping review surface. Manages local draft state for the
// PENDING_REVIEW edit path; renders read-only for any other status.
// LLM-off path is first-class (per Phase 5c.1b acceptance): different
// header, different helper copy, no proposal column — but the same
// layout language, the same dropdown, the same confirm flow. A tenant
// who has only ever seen the LLM-off path wouldn't know they were
// "missing" anything.
export function MappingReviewView({ upload }: Props) {
  const router = useRouter();
  const schemaQuery = useCanonicalSchema();
  const settingsQuery = useDisSettings();
  const confirmMutation = useConfirmMapping(upload.id);

  const llmOn = upload.llm_proposal_metadata.enabled;
  const editable = upload.status === "PENDING_REVIEW";

  // Discriminate "off because tenant turned it off" (capability=true,
  // opt_in=false → show "Manage in DIS settings" link) from "off
  // because plan doesn't include LLM-assist" (capability=false → no
  // settings link; admin contact is the only path).
  const offBecauseOptOut =
    !llmOn && (settingsQuery.data?.llm_assist.capability ?? true) === true;

  // Initial draft seeded from existing column_mappings:
  //   - currentMapping carries any prior pick (null in fresh PENDING_REVIEW)
  //   - ignored carries the ignored flag
  // Tenant edits operate against this client-side draft until Confirm.
  const initialDraft = useMemo(() => {
    const mappings: Record<string, string | null> = {};
    const ignored = new Set<string>();
    for (const c of upload.column_mappings) {
      mappings[c.source_column] = c.current_mapping;
      if (c.ignored) ignored.add(c.source_column);
    }
    return { mappings, ignored };
  }, [upload.column_mappings]);

  const [draftMappings, setDraftMappings] = useState<Record<string, string | null>>(
    initialDraft.mappings,
  );
  const [ignored, setIgnored] = useState<Set<string>>(initialDraft.ignored);
  const [submitError, setSubmitError] = useState<string | null>(null);

  function setMapping(col: string, fieldId: string | null) {
    setDraftMappings((prev) => ({ ...prev, [col]: fieldId }));
  }

  function toggleIgnored(col: string) {
    setIgnored((prev) => {
      const next = new Set(prev);
      if (next.has(col)) next.delete(col);
      else {
        next.add(col);
        // Ignoring a column clears any prior mapping draft so the
        // confirm payload doesn't carry conflicting state.
        setDraftMappings((p) => ({ ...p, [col]: null }));
      }
      return next;
    });
  }

  const unmappedCount = useMemo(() => {
    return upload.column_mappings.reduce((acc, c) => {
      if (ignored.has(c.source_column)) return acc;
      return draftMappings[c.source_column] ? acc : acc + 1;
    }, 0);
  }, [upload.column_mappings, draftMappings, ignored]);

  // Phase 5c.1b hotfix: require at least one column. Without this,
  // an upload with empty column_mappings (truly unparseable file, or
  // pre-hotfix upload created before the heuristic mapper landed) had
  // unmappedCount === 0 vacuously, enabling Confirm with zero mappings.
  const hasColumns = upload.column_mappings.length > 0;
  const canConfirm = hasColumns && unmappedCount === 0;

  async function onConfirm() {
    setSubmitError(null);
    const mappings: Record<string, string> = {};
    for (const c of upload.column_mappings) {
      if (ignored.has(c.source_column)) continue;
      const fieldId = draftMappings[c.source_column];
      if (fieldId) mappings[c.source_column] = fieldId;
    }
    try {
      await confirmMutation.mutateAsync({
        mappings,
        ignored_columns: Array.from(ignored),
      });
      router.push("/dis/uploads");
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Confirm failed. Try again.");
    }
  }

  if (schemaQuery.isLoading) {
    return <Skeleton variant="row" count={6} />;
  }
  if (schemaQuery.error || !schemaQuery.data) {
    return (
      <ErrorInline
        message="Could not load canonical schema."
        onRetry={() => schemaQuery.refetch()}
      />
    );
  }
  const schema = schemaQuery.data.domains;

  return (
    <div className="flex flex-col rounded-md border border-border bg-card/20">
      <div className="flex items-start gap-3 border-b border-border px-6 py-4">
        <span
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground"
          aria-hidden="true"
        >
          {llmOn ? <Sparkles className="h-4 w-4" /> : <Pencil className="h-4 w-4" />}
        </span>
        <div className="flex flex-col gap-0.5">
          <h2 className="text-subheading">
            {llmOn ? "Review LLM-proposed mappings" : "Map columns to canonical fields"}
          </h2>
          <p className="text-caption text-muted-foreground">
            {llmOn
              ? "Each column shows the model's best guess and confidence. Override anything that looks off, ignore columns you don't need, then confirm to start ingest."
              : "Pick a canonical field for each column. Ignore columns that don't belong in the schema. Confirm to start ingest."}
          </p>
          {offBecauseOptOut ? (
            // Hotfix after 5c.1c smoke: a Next.js <Link href="/dis/settings">
            // here was navigating to /dis/dashboard/settings under some
            // dev-server states. Switched to explicit router.push to
            // eliminate any path-resolution ambiguity. Sidebar entry
            // added in the same hotfix is now the primary discovery
            // path; this contextual link is redundant but kept for
            // affordance from the LLM-off header itself.
            <button
              type="button"
              onClick={() => router.push("/dis/settings")}
              className="mt-1 inline-flex w-fit items-center gap-1 text-caption text-primary hover:underline"
            >
              Manage in DIS settings
              <ExternalLink className="h-3 w-3" />
            </button>
          ) : null}
        </div>
      </div>

      {hasColumns ? (
        <ul className="flex flex-col">
          {upload.column_mappings.map((c) => (
            <ColumnMappingRow
              key={c.source_column}
              column={c}
              schema={schema}
              readOnly={!editable}
              draftMapping={draftMappings[c.source_column] ?? null}
              draftIgnored={ignored.has(c.source_column)}
              onMappingChange={(fieldId) => setMapping(c.source_column, fieldId)}
              onToggleIgnored={() => toggleIgnored(c.source_column)}
            />
          ))}
        </ul>
      ) : (
        // Defensive: heuristic mapper synthesizes columns for any
        // parsed CSV; this state is only reachable for non-CSV
        // uploads without a parser path or for pre-hotfix records
        // created before the synthesis logic landed.
        <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
          <p className="text-sm font-medium">No columns detected</p>
          <p className="text-caption text-muted-foreground">
            The file may be empty, not a CSV, or formatted in a way the v1
            parser can&apos;t read. Re-upload as CSV with a header row, or
            cancel and try a different file.
          </p>
        </div>
      )}

      {hasColumns ? (
        <SampleRowsTable
          uploadId={upload.id}
          columns={upload.column_mappings}
          activeMappings={editable ? draftMappings : Object.fromEntries(
            upload.column_mappings.map((c) => [c.source_column, c.current_mapping]),
          )}
          schema={schema}
        />
      ) : null}

      {submitError ? (
        <div className="px-6 pt-3">
          <ErrorInline message={submitError} />
        </div>
      ) : null}

      {editable ? (
        <MappingActions
          canConfirm={canConfirm}
          confirming={confirmMutation.isPending}
          unmappedCount={unmappedCount}
          onConfirm={onConfirm}
          onCancel={() => router.push("/dis/uploads")}
        />
      ) : (
        <div className="border-t border-border bg-card/30 px-6 py-3 text-caption text-muted-foreground">
          Mapping confirmed; this view is read-only.
        </div>
      )}
    </div>
  );
}
