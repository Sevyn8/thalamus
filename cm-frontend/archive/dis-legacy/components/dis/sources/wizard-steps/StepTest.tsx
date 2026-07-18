"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, SkipForward, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useTestConnection } from "@/lib/dis/hooks/use-sources";
import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import type {
  ConnectionConfig,
  SystemKind,
  TestConnectionResult,
} from "@/types/dis";

type Props = {
  type: SystemKind;
  config: Partial<ConnectionConfig>;
  // Wizard reads this to gate Next: enabled on success OR skip.
  onResultChange: (succeeded: boolean) => void;
  // Phase 5c.2c3: skip-test propagation. Wizard tracks separately so
  // the create/update payload can record untested_at_creation.
  onSkipChange: (skipped: boolean) => void;
  onBackToConfig: () => void;
};

// Phase 5c.2c3: skip-test option added per A1. Skip button alongside
// Test, always visible from the start (not gated on a prior failure).
// Tenants who know their config is right shouldn't have to fail-then-
// skip; tenants who hit a transient mock failure but want to proceed
// can skip explicitly with the warning visible.

export function StepTest({
  type,
  config,
  onResultChange,
  onSkipChange,
  onBackToConfig,
}: Props) {
  const mutation = useTestConnection();
  const [result, setResult] = useState<TestConnectionResult | null>(null);
  const [skipped, setSkipped] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);

  useEffect(() => {
    onResultChange(result?.success === true);
  }, [result, onResultChange]);

  useEffect(() => {
    onSkipChange(skipped);
  }, [skipped, onSkipChange]);

  async function runTest() {
    setRequestError(null);
    setSkipped(false);
    try {
      const r = await mutation.mutateAsync({ type, connection_config: config });
      setResult(r);
    } catch (err) {
      setResult(null);
      setRequestError(
        err instanceof ApiError ? err.message : "Test request failed. Try again.",
      );
    }
  }

  function skip() {
    setRequestError(null);
    setResult(null);
    setSkipped(true);
  }

  function back() {
    setResult(null);
    setRequestError(null);
    setSkipped(false);
    onBackToConfig();
  }

  const idle = result === null && !skipped && !mutation.isPending && !requestError;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-caption text-muted-foreground">
        Verify the configuration can reach the source before saving. v1
        simulates the test; real backend exercises the actual connector
        in Phase 5d.
      </p>

      {idle ? (
        <div className="flex items-center gap-2">
          <Button onClick={runTest}>Test connection</Button>
          <Button variant="ghost" onClick={skip}>
            <SkipForward className="h-4 w-4" />
            Skip — untested at creation
          </Button>
        </div>
      ) : null}

      {mutation.isPending ? (
        <div className="flex items-center gap-2 rounded-md border border-border bg-card/30 p-4 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Testing connection…
        </div>
      ) : null}

      {result?.success === true ? (
        <div className="flex items-start gap-3 rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="flex flex-col gap-2">
            <span className="font-medium">Connection succeeded.</span>
            <span>Continue to schedule.</span>
            <Button
              variant="outline"
              size="sm"
              onClick={runTest}
              className={cn("w-fit", "border-emerald-300 dark:border-emerald-500/40")}
            >
              <RefreshCw className="h-4 w-4" />
              Test again
            </Button>
          </div>
        </div>
      ) : null}

      {result && result.success === false ? (
        <div className="flex items-start gap-3 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="flex flex-col gap-2">
            <span className="font-medium">{result.error_code}</span>
            <span>{result.error_message}</span>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={runTest}
                className="border-red-300 dark:border-red-500/40"
              >
                <RefreshCw className="h-4 w-4" />
                Retry
              </Button>
              <Button variant="ghost" size="sm" onClick={skip}>
                <SkipForward className="h-4 w-4" />
                Skip
              </Button>
              <Button variant="ghost" size="sm" onClick={back}>
                Back to config
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {skipped ? (
        <div className="flex items-start gap-3 rounded-md border border-amber-300 bg-amber-50 p-4 text-sm text-amber-700 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="flex flex-col gap-2">
            <span className="font-medium">Test skipped.</span>
            <span>
              Untested — may fail on first run. The source will be flagged
              <span className="font-mono"> untested_at_creation</span>.
            </span>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={runTest} className="border-amber-300 dark:border-amber-500/40">
                <RefreshCw className="h-4 w-4" />
                Test now
              </Button>
              <Button variant="ghost" size="sm" onClick={back}>
                Back to config
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {requestError ? (
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          {requestError}
        </div>
      ) : null}
    </div>
  );
}
