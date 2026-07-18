"use client";

import { useState } from "react";

import { Switch } from "@/components/ui/switch";
import { comingInV1 } from "@/components/shared/ComingInV1Toast";

const FLIP_HOLD_MS = 700;

type PrefRowProps = {
  label: string;
  description: string;
  defaultOn: boolean;
  feature: string;
};

function PrefRow({ label, description, defaultOn, feature }: PrefRowProps) {
  const [flipped, setFlipped] = useState(false);
  const visiblyOn = flipped ? !defaultOn : defaultOn;

  function toggle() {
    setFlipped(true);
    comingInV1(feature);
    setTimeout(() => setFlipped(false), FLIP_HOLD_MS);
  }

  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <div className="flex flex-col">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-xs text-muted-foreground">{description}</span>
      </div>
      <Switch
        checked={visiblyOn}
        onCheckedChange={toggle}
        aria-label={`Toggle ${label}`}
      />
    </div>
  );
}

export function ProfileNotificationPrefs() {
  return (
    <section className="flex flex-col gap-1 rounded-md border border-border bg-card/30 p-6">
      <h2 className="text-label text-muted-foreground">
        Notification preferences
      </h2>
      <div className="divide-y divide-border">
        <PrefRow
          label="In-app notifications"
          description="Show alerts in the top bar and inbox."
          defaultOn={true}
          feature="In-app notifications preference"
        />
        <PrefRow
          label="Email notifications"
          description="Send daily digest to your inbox."
          defaultOn={true}
          feature="Email notifications preference"
        />
      </div>
    </section>
  );
}
