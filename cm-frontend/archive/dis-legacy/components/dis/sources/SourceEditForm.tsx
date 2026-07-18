"use client";

import { useId, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { ApiError } from "@/lib/api/client";
import { useSource, useUpdateSource } from "@/lib/dis/hooks/use-sources";
import type { ConnectionConfig } from "@/types/dis";

import { SystemKindChip } from "@/components/dis/chips/SystemKindChip";
import { StepConfig } from "./wizard-steps/StepConfig";

// Phase 5c.2c1: edit form. Reuses StepConfig (the wizard's per-type
// form switchboard) for the connection_config block — single source
// of truth for the 9 form variants. Type and org_node are immutable
// post-creation per Sb/Sc, so they render as read-only chips/labels.
//
// Phase 5e.4e: Schedule input removed. Per-feed cadence lives on
// Stream (edited via the Stream-level PATCH endpoint in 5e.4d).
// SourceEditForm narrows to system-identity edits: name + credentials.

type Props = {
  sourceId: string;
};

export function SourceEditForm({ sourceId }: Props) {
  const router = useRouter();
  const query = useSource(sourceId);
  const update = useUpdateSource(sourceId);

  if (query.isLoading) {
    return <Skeleton variant="row" count={6} />;
  }
  if (query.error || !query.data) {
    return (
      <ErrorInline
        message="Could not load source for editing."
        onRetry={() => query.refetch()}
      />
    );
  }

  return <Body source={query.data} update={update} router={router} />;
}

type BodyProps = {
  source: ReturnType<typeof useSource>["data"] & object;
  update: ReturnType<typeof useUpdateSource>;
  router: ReturnType<typeof useRouter>;
};

function Body({ source, update, router }: BodyProps) {
  const [name, setName] = useState(source.name);
  const [connectionConfig, setConnectionConfig] = useState<Partial<ConnectionConfig>>(
    source.connection_config as Partial<ConnectionConfig>,
  );
  const [configValid, setConfigValid] = useState(
    Object.keys(source.connection_config).length > 0,
  );
  const [submitError, setSubmitError] = useState<string | null>(null);
  const nameId = useId();

  const canSave =
    name.trim().length > 0 && configValid && !update.isPending;

  async function onSave() {
    if (!canSave) return;
    setSubmitError(null);
    try {
      await update.mutateAsync({
        name: name.trim(),
        connection_config: connectionConfig as Record<string, unknown>,
      });
      router.push(`/dis/sources/${source.id}`);
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Save failed. Try again.");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 rounded-md border border-border bg-card/30 p-4">
        <div className="flex flex-col gap-1.5">
          <span className="text-label text-muted-foreground">Type</span>
          <span className="text-sm">
            <SystemKindChip type={source.type} />
          </span>
          <span className="text-caption text-muted-foreground">Type cannot be changed after creation.</span>
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-label text-muted-foreground">Org node</span>
          <span className="text-sm">
            {source.org_node_code ? (
              <span className="font-mono">{source.org_node_code}</span>
            ) : (
              <span className="text-muted-foreground">—</span>
            )}
          </span>
          <span className="text-caption text-muted-foreground">Org node cannot be changed after creation.</span>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor={nameId} className="text-label text-muted-foreground">
          Source name
        </label>
        <Input
          id={nameId}
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={120}
        />
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-label text-muted-foreground">Connection config</span>
        <StepConfig
          type={source.type}
          value={connectionConfig}
          onChange={(next, valid) => {
            setConnectionConfig(next);
            setConfigValid(valid);
          }}
        />
      </div>

      {submitError ? <ErrorInline message={submitError} /> : null}

      <div className="flex items-center justify-between gap-3 border-t border-border pt-4">
        <Button variant="ghost" onClick={() => router.push(`/dis/sources/${source.id}`)}>
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
