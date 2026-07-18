"use client";

import { Input } from "@/components/ui/input";
import type { SystemKind } from "@/types/dis";

// Phase 5e.4d: simpler Step 5 for AddSourceWizard. Pre-split this was
// StepSchedule and combined cron + name + review; post-split schedule
// belongs to Stream. This step collects just the source's display
// name and renders a Review card summarizing all wizard selections.

type Props = {
  name: string;
  type: SystemKind;
  orgNodeLabel: string | null;
  onNameChange: (next: string) => void;
};

export function StepSourceName({
  name,
  type,
  orgNodeLabel,
  onNameChange,
}: Props) {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <label className="text-label text-muted-foreground">Source name</label>
        <Input
          type="text"
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          placeholder="e.g. Warsaw HQ POS feed"
          maxLength={120}
        />
        <p className="text-caption text-muted-foreground">
          The system identity name (the credentialed external system
          itself). Each data feed under this source gets its own name
          when you add the stream.
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-label text-muted-foreground">Review</span>
        <div className="grid grid-cols-1 gap-3 rounded-md border border-border bg-card/30 p-4 sm:grid-cols-2">
          <ReviewItem label="Name" value={name || "—"} />
          <ReviewItem label="System" value={type} />
          <ReviewItem label="Org node" value={orgNodeLabel ?? "—"} />
        </div>
        <p className="text-caption text-muted-foreground">
          After save, you&apos;ll land on the source detail page where
          you can add the first stream (data feed) under this source.
        </p>
      </div>
    </div>
  );
}

function ReviewItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-label text-muted-foreground">{label}</span>
      <span className="text-sm">{value}</span>
    </div>
  );
}
