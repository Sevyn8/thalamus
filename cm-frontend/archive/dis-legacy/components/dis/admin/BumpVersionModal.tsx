"use client";

import { useId, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { useBumpCanonicalVersion } from "@/lib/dis/hooks/use-canonical-schema";
import { classifyChange } from "@/lib/dis/canonical-schema-classifier";
import { recordAuditEvent } from "@/lib/dis/audit";
import type { CanonicalSchemaDomain, PendingChangeWire } from "@/types/dis";

// Phase 5c.8b2: aggregates the domain's pending changes (overrides
// + added fields since last bump), runs the 5c.8b1 classifier per
// edit, suggests a next version per semver, and posts the bump.
// Single classifier output rules: any breaking → MAJOR; else any
// additive → MINOR; else PATCH. New fields count as additive.
//
// Real backend will likely compute pending changes server-side and
// emit a typed bump request shape; v1's modal reads pending_changes
// off the domain record (server includes via readPendingChanges).

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  domain: CanonicalSchemaDomain;
};

type Aggregate = {
  breaking: number;
  additive: number;
  neutral: number;
  kind: "additive" | "breaking" | "neutral";
};

function aggregate(pending: PendingChangeWire[]): Aggregate {
  let breaking = 0;
  let additive = 0;
  let neutral = 0;
  for (const p of pending) {
    if (p.kind === "add") {
      additive++;
      continue;
    }
    const result = classifyChange(p.before_field, p.override);
    if (result.kind === "breaking") breaking++;
    else if (result.kind === "additive") additive++;
    else neutral++;
  }
  const kind: Aggregate["kind"] =
    breaking > 0 ? "breaking" : additive > 0 ? "additive" : "neutral";
  return { breaking, additive, neutral, kind };
}

// Parse "v1" / "v1.2" / "v1.2.3" → [major, minor, patch]; missing
// segments default to 0. Accepts the leading "v" prefix or none.
function parseVersion(v: string | undefined): [number, number, number] {
  if (!v) return [1, 0, 0];
  const stripped = v.replace(/^v/i, "");
  const parts = stripped.split(".").map((s) => Number.parseInt(s, 10));
  return [parts[0] || 0, parts[1] || 0, parts[2] || 0];
}

function formatVersion([maj, min, pat]: [number, number, number]): string {
  if (pat > 0) return `v${maj}.${min}.${pat}`;
  if (min > 0) return `v${maj}.${min}`;
  return `v${maj}`;
}

function suggestNext(
  current: string | undefined,
  kind: Aggregate["kind"],
): string {
  const [maj, min, pat] = parseVersion(current);
  if (kind === "breaking") return formatVersion([maj + 1, 0, 0]);
  if (kind === "additive") return formatVersion([maj, min + 1, 0]);
  return formatVersion([maj, min, pat + 1]);
}

export function BumpVersionModal({ open, onOpenChange, domain }: Props) {
  const bumpMutation = useBumpCanonicalVersion();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const versionInputId = useId();

  const pending: PendingChangeWire[] = useMemo(
    () => domain.pending_changes ?? [],
    [domain.pending_changes],
  );
  const summary = useMemo(() => aggregate(pending), [pending]);
  const suggested = useMemo(
    () => suggestNext(domain.version, summary.kind),
    [domain.version, summary.kind],
  );

  // Local input state seeded from the suggestion. Keying on the
  // domain id + open ensures a fresh seed each time the modal opens
  // or the domain changes.
  const [nextVersion, setNextVersion] = useState(suggested);
  const [seedKey, setSeedKey] = useState(`${domain.id}|${suggested}`);
  const currentSeedKey = `${domain.id}|${suggested}`;
  if (seedKey !== currentSeedKey) {
    setSeedKey(currentSeedKey);
    setNextVersion(suggested);
  }

  const isPending = bumpMutation.isPending;
  const noChanges = pending.length === 0;
  const isVersionFormatOk = /^v?\d+(\.\d+){0,2}$/.test(nextVersion.trim());
  const canSubmit = !noChanges && isVersionFormatOk && nextVersion.trim().length > 0;

  async function handleSave(): Promise<void> {
    setSubmitError(null);
    if (!canSubmit) return;
    const formatted = nextVersion.trim().startsWith("v")
      ? nextVersion.trim()
      : `v${nextVersion.trim()}`;
    try {
      await bumpMutation.mutateAsync({
        domainId: domain.id,
        input: {
          next_version: formatted,
          change_count: pending.length,
          kind: summary.kind,
        },
      });
      recordAuditEvent({
        event_type: "canonical_schema_version_bumped",
        domain_id: domain.id,
        prev_version: domain.version ?? "",
        next_version: formatted,
        change_count: pending.length,
        kind: summary.kind,
      });
      onOpenChange(false);
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Bump failed. Try again.",
      );
    }
  }

  const kindTone =
    summary.kind === "breaking"
      ? "border-red-200 bg-red-50 text-red-900 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-200"
      : summary.kind === "additive"
        ? "border-blue-200 bg-blue-50 text-blue-900 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-200"
        : "border-border bg-card/50 text-muted-foreground";
  const kindLabel =
    summary.kind === "breaking"
      ? "Breaking impact"
      : summary.kind === "additive"
        ? "Additive impact"
        : "Neutral impact";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Bump canonical schema version</DialogTitle>
          <DialogDescription>
            {domain.name} ·{" "}
            <span className="font-mono">{domain.version ?? "v1"}</span>
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          {noChanges ? (
            <div className="rounded-md border border-dashed border-border bg-muted/30 p-3 text-sm text-muted-foreground">
              No pending changes since the last bump. Edit fields or add new
              ones first.
            </div>
          ) : (
            <div className={`flex flex-col gap-1 rounded-md border p-3 ${kindTone}`}>
              <span className="text-label">{kindLabel}</span>
              <p className="text-sm">
                {summary.breaking > 0
                  ? `${summary.breaking} breaking · `
                  : ""}
                {summary.additive > 0
                  ? `${summary.additive} additive · `
                  : ""}
                {summary.neutral > 0 ? `${summary.neutral} neutral` : ""}
                {summary.breaking + summary.additive + summary.neutral === 0
                  ? "no schema-shape changes"
                  : ""}
              </p>
            </div>
          )}

          <div className="flex flex-col gap-2">
            <label
              htmlFor={versionInputId}
              className="text-label text-muted-foreground"
            >
              Next version
            </label>
            <Input
              id={versionInputId}
              value={nextVersion}
              onChange={(e) => setNextVersion(e.target.value)}
              className="font-mono"
              placeholder={suggested}
              disabled={noChanges}
            />
            <span className="text-caption text-muted-foreground">
              Suggested: <span className="font-mono">{suggested}</span> based on
              the aggregated impact.
            </span>
            {!isVersionFormatOk && nextVersion.length > 0 ? (
              <span className="text-caption text-danger">
                Invalid version format. Use v1 / v1.2 / v1.2.3.
              </span>
            ) : null}
          </div>

          {submitError ? <ErrorInline message={submitError} /> : null}
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            disabled={isPending}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={isPending || !canSubmit}>
            {isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Bumping…
              </>
            ) : (
              "Bump version"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
