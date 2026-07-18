"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Pause, Play, RefreshCw, RotateCcw, Trash2, UserCog } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ConfirmDestructive } from "@/components/shared/ConfirmDestructive";
import { ApiError } from "@/lib/api/client";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { recordAuditEvent } from "@/lib/dis/audit";
import {
  useDeleteSource,
  usePauseSource,
  useResumeSource,
  useRotateCredentials,
  useRunNow,
} from "@/lib/dis/hooks/use-sources";
import type { Source } from "@/types/dis";

import { ReassignOwnershipModal } from "./ReassignOwnershipModal";

// Phase 5c.2c1: lifecycle action buttons on /dis/sources/[id].
//
// Visibility per A5 final:
//   - Pause: only when ACTIVE
//   - Resume: only when PAUSED
//   - Run now: only when ACTIVE
//   - Rotate credentials: only when source has credentials_ref in
//     connection_config (POS_API_GENERIC, FTP, REST_API_GENERIC)
//   - Delete: ALWAYS visible (escape hatch — abandon ERROR sources,
//     remove finished PAUSED sources, etc.). Gated by
//     ConfirmDestructive with type-to-confirm of source name.
//
// Reversible actions fire immediately, no confirmation. Delete uses
// the established 5b.1 ConfirmDestructive pattern.

type Props = {
  source: Source;
};

function hasCredentialsRef(source: Source): boolean {
  return (
    source.connection_config &&
    typeof source.connection_config === "object" &&
    "credentials_ref" in source.connection_config
  );
}

export function SourceLifecycleActions({ source }: Props) {
  const router = useRouter();
  const snapshot = useAuthSnapshot();
  const isPlatform = snapshot?.user.userType === "PLATFORM";
  const pause = usePauseSource(source.id);
  const resume = useResumeSource(source.id);
  const runNow = useRunNow(source.id);
  const rotate = useRotateCredentials(source.id);
  const del = useDeleteSource(source.id);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [reassignOpen, setReassignOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  function wrapErr<T>(fn: () => Promise<T>) {
    return async () => {
      setActionError(null);
      try {
        await fn();
      } catch (err) {
        setActionError(err instanceof ApiError ? err.message : "Action failed.");
      }
    };
  }

  // Phase 5c.2c2: Platform-persona pause records an audit event
  // tagging the action as cross-ownership-boundary. Tenant-persona
  // pause is unaudited (own-tenant action). Same /pause endpoint
  // underneath; just different label + audit metadata per Sa.
  async function pauseAction() {
    setActionError(null);
    try {
      await pause.mutateAsync();
      if (isPlatform) {
        recordAuditEvent({
          event_type: "admin_force_pause",
          source_id: source.id,
          source_name: source.name,
          source_tenant_id: source.tenant_id,
        });
      }
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Action failed.");
    }
  }

  // Phase 5c.3a: Run now creates a real Run record (instead of just
  // bumping last_run_at as in 5c.2c1). Toast surfaces the row count
  // so the user sees something concrete; the new run also appears at
  // the top of the Runs tab via the runs query invalidation.
  //
  // Toast wording per A15 hotfix: avoids "completed in {duration}"
  // since v1's instant-SUCCEEDED simulation has no real elapsed
  // duration. When real backend lands (Phase 4b-runs), the mutation
  // returns RUNNING and the toast naturally evolves.
  async function runNowAction() {
    setActionError(null);
    try {
      const run = await runNow.mutateAsync();
      toast.success(
        `Run completed — ${(run.rows_ingested ?? 0).toLocaleString()} rows`,
      );
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Action failed.");
    }
  }

  async function onConfirmDelete() {
    setActionError(null);
    try {
      await del.mutateAsync();
      router.push("/dis/sources");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Delete failed.");
      throw err;
    }
  }

  const showPause = source.status === "ACTIVE";
  const showResume = source.status === "PAUSED";
  const showRunNow = source.status === "ACTIVE";
  const showRotate = hasCredentialsRef(source);

  const anyPending =
    pause.isPending || resume.isPending || runNow.isPending || rotate.isPending || del.isPending;

  return (
    <div className="flex flex-col gap-2">
      {/* Lifecycle row: operational state transitions. Buttons hide
          by status per A5 (Pause/Resume/RunNow); Rotate hides by
          connector type; Delete is always visible. */}
      <div className="flex items-center gap-2 flex-wrap">
        {showPause ? (
          <Button
            variant="outline"
            size="sm"
            onClick={pauseAction}
            disabled={anyPending}
          >
            {pause.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Pause className="h-4 w-4" />}
            {isPlatform ? "Force pause" : "Pause"}
          </Button>
        ) : null}
        {showResume ? (
          <Button
            variant="outline"
            size="sm"
            onClick={wrapErr(() => resume.mutateAsync())}
            disabled={anyPending}
          >
            {resume.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Resume
          </Button>
        ) : null}
        {showRunNow ? (
          <Button
            variant="outline"
            size="sm"
            onClick={runNowAction}
            disabled={anyPending}
          >
            {runNow.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Run now
          </Button>
        ) : null}
        {showRotate ? (
          <Button
            variant="outline"
            size="sm"
            onClick={wrapErr(() => rotate.mutateAsync())}
            disabled={anyPending}
          >
            {rotate.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
            Rotate credentials
          </Button>
        ) : null}
        <Button
          variant="outline"
          size="sm"
          onClick={() => setConfirmOpen(true)}
          disabled={anyPending}
          className="ml-auto text-danger hover:text-danger"
        >
          <Trash2 className="h-4 w-4" />
          Delete
        </Button>
      </div>

      {/* Governance row: admin actions independent of operational
          state. Phase 5c.2c2 hotfix: Reassign was originally placed
          in the lifecycle row, which made its visibility appear
          status-conditional under flex-wrap reflow. Pulled out into
          a dedicated row to make the semantic separation visible AND
          eliminate any flex-wrap interaction with status changes.
          Visibility gated only on isPlatform — reassignment works
          across ACTIVE/PAUSED/ERROR/ONBOARDING/COMPLETED/etc. */}
      {isPlatform ? (
        <div className="flex items-center gap-2 border-t border-border pt-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setReassignOpen(true)}
            disabled={anyPending}
          >
            <UserCog className="h-4 w-4" />
            Reassign ownership
          </Button>
        </div>
      ) : null}

      {actionError ? (
        <p className="text-caption text-danger" role="alert">
          {actionError}
        </p>
      ) : null}

      <ConfirmDestructive
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={`Delete ${source.name}?`}
        description="This permanently removes the source and stops any further ingest. Active runs are not affected; historical run records remain."
        confirmText={source.name}
        confirmLabel="Delete source"
        onConfirm={onConfirmDelete}
      />

      {isPlatform ? (
        <ReassignOwnershipModal
          source={source}
          open={reassignOpen}
          onOpenChange={setReassignOpen}
        />
      ) : null}
    </div>
  );
}
