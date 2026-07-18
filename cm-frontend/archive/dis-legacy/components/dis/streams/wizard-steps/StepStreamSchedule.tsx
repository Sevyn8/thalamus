"use client";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// Phase 5e.4d step 3: cron schedule + presets. Same shape as the
// pre-5e.4d StepSchedule cron section (sources wizard's step 5),
// extracted to its stream-scoped location since schedule belongs to
// Stream now. CRON_RE matches the source-edit form validator
// (CRON_RE in SourceEditForm). Real backend may use stricter parsing
// or accept extended formats; v1 stays narrow.

const CRON_RE = /^\s*([0-9*,/-]+)\s+([0-9*,/-]+)\s+([0-9*,/-]+)\s+([0-9*,/-]+)\s+([0-9*,/-]+)\s*$/;

const PRESETS: Array<{ label: string; expr: string }> = [
  { label: "Hourly", expr: "0 * * * *" },
  { label: "Daily 06:00", expr: "0 6 * * *" },
  { label: "Weekly Monday 06:00", expr: "0 6 * * 1" },
];

type Props = {
  schedule: string;
  onScheduleChange: (next: string) => void;
};

export function StepStreamSchedule({ schedule, onScheduleChange }: Props) {
  const cronValid = CRON_RE.test(schedule);
  const showCronError = schedule.length > 0 && !cronValid;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-caption text-muted-foreground">
        How often should this stream ingest? Standard 5-token cron;
        presets cover common cadences.
      </p>
      <div className="flex flex-col gap-2">
        <label className="text-label text-muted-foreground">Schedule (cron)</label>
        <Input
          type="text"
          value={schedule}
          onChange={(e) => onScheduleChange(e.target.value)}
          placeholder="0 * * * *"
          className={cn(showCronError && "border-danger")}
          aria-invalid={showCronError}
        />
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <Button
              key={p.label}
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onScheduleChange(p.expr)}
            >
              {p.label}
            </Button>
          ))}
        </div>
        {showCronError ? (
          <p className="text-caption text-danger" role="alert">
            Schedule must be a 5-token cron expression (e.g. <code>0 6 * * 1</code>).
          </p>
        ) : null}
      </div>
    </div>
  );
}

export function isCronValid(schedule: string): boolean {
  return CRON_RE.test(schedule);
}
