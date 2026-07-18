"use client";

import { useState } from "react";
import { Loader2, Pause, Play, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { ApiError } from "@/lib/api/client";
import {
  usePauseStream,
  useResumeStream,
  useRunStreamNow,
} from "@/lib/dis/hooks/use-streams";
import type { Stream } from "@/types/dis";

// Phase 5e.4d: thin per-stream lifecycle actions. Mirrors
// SourceLifecycleActions but stripped of system-only concerns
// (Delete, Rotate credentials, Reassign ownership). Three actions:
//
//   - Run now: ACTIVE only — primary
//   - Pause:   ACTIVE only
//   - Resume:  PAUSED only
//
// Delete + Reassign defer to 5e.4e (or stay permanently absent at the
// stream level — owner inherits from source, system-identity concerns
// don't belong on the feed surface).

type Props = {
  stream: Stream;
};

export function StreamLifecycleActions({ stream }: Props) {
  const pause = usePauseStream(stream.id);
  const resume = useResumeStream(stream.id);
  const runNow = useRunStreamNow(stream.id);

  const [actionError, setActionError] = useState<string | null>(null);

  function wrapErr<T>(fn: () => Promise<T>, successToast?: string) {
    return async () => {
      setActionError(null);
      try {
        const result = await fn();
        if (successToast) toast.success(successToast);
        return result;
      } catch (err) {
        setActionError(err instanceof ApiError ? err.message : "Action failed.");
      }
    };
  }

  const canRunNow = stream.status === "ACTIVE";
  const canPause = stream.status === "ACTIVE";
  const canResume = stream.status === "PAUSED";

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {canRunNow ? (
          <Button
            onClick={wrapErr(
              () => runNow.mutateAsync(),
              "Run completed — new row in Runs.",
            )}
            disabled={runNow.isPending}
          >
            {runNow.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Run now
          </Button>
        ) : null}
        {canPause ? (
          <Button
            variant="outline"
            onClick={wrapErr(() => pause.mutateAsync())}
            disabled={pause.isPending}
          >
            <Pause className="h-4 w-4" />
            Pause
          </Button>
        ) : null}
        {canResume ? (
          <Button
            variant="outline"
            onClick={wrapErr(() => resume.mutateAsync())}
            disabled={resume.isPending}
          >
            <Play className="h-4 w-4" />
            Resume
          </Button>
        ) : null}
      </div>
      {actionError ? <ErrorInline message={actionError} /> : null}
    </div>
  );
}
