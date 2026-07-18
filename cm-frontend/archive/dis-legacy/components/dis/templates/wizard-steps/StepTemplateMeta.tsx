"use client";

import { useId } from "react";

import { Input } from "@/components/ui/input";
import type { TemplateVisibility } from "@/types/dis";

// Phase 5e.6 step 2: name + description + visibility. Standalone
// inputs (no Form wrapper) — wizard chrome handles canAdvance gating.

type Props = {
  name: string;
  description: string;
  visibility: TemplateVisibility;
  onNameChange: (next: string) => void;
  onDescriptionChange: (next: string) => void;
  onVisibilityChange: (next: TemplateVisibility) => void;
};

export function StepTemplateMeta({
  name,
  description,
  visibility,
  onNameChange,
  onDescriptionChange,
  onVisibilityChange,
}: Props) {
  const nameId = useId();
  const descId = useId();
  const privId = useId();
  const sharedId = useId();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <label htmlFor={nameId} className="text-label text-muted-foreground">
          Template name
        </label>
        <Input
          id={nameId}
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          placeholder="e.g. Daily Sales + Inventory + Products"
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
          onChange={(e) => onDescriptionChange(e.target.value)}
          placeholder="What does this Super Template combine? Who uses it and how often?"
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
              name="visibility"
              value="TENANT_SHARED"
              checked={visibility === "TENANT_SHARED"}
              onChange={() => onVisibilityChange("TENANT_SHARED")}
              className="mt-0.5"
            />
            <span className="flex flex-col gap-0.5">
              <span className="text-sm font-medium">Tenant-shared</span>
              <span className="text-caption text-muted-foreground">
                Anyone in your tenant can apply this template on upload.
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
              name="visibility"
              value="PRIVATE"
              checked={visibility === "PRIVATE"}
              onChange={() => onVisibilityChange("PRIVATE")}
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
    </div>
  );
}
