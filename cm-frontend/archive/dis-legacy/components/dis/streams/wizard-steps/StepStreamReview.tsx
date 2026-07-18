"use client";

import { Input } from "@/components/ui/input";
import type { Source, StreamDomain } from "@/types/dis";

// Phase 5e.4d step 4: name input + final review card. Mirrors
// StepSourceName's shape (name + review) but with stream-context
// review items (source / domain / schedule).

type Props = {
  name: string;
  source: Source;
  domain: StreamDomain;
  schedule: string;
  onNameChange: (next: string) => void;
};

export function StepStreamReview({
  name,
  source,
  domain,
  schedule,
  onNameChange,
}: Props) {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <label className="text-label text-muted-foreground">Stream name</label>
        <Input
          type="text"
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          placeholder={`e.g. ${source.name} — ${domain}`}
          maxLength={120}
        />
        <p className="text-caption text-muted-foreground">
          A human-readable name for this data feed. Convention:{" "}
          <span className="font-mono text-xs">
            {"{source}"} — {"{domain}"}
          </span>{" "}
          (e.g. &ldquo;{source.name} — {domain}&rdquo;).
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-label text-muted-foreground">Review</span>
        <div className="grid grid-cols-1 gap-3 rounded-md border border-border bg-card/30 p-4 sm:grid-cols-2">
          <ReviewItem label="Name" value={name || "—"} />
          <ReviewItem label="Source" value={source.name} />
          <ReviewItem label="Domain" value={domain} />
          <ReviewItem label="Schedule" value={schedule || "—"} />
        </div>
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
