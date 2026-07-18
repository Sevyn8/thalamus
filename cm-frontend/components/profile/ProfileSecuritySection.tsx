"use client";

import { Button } from "@/components/ui/button";
import { comingInV1 } from "@/components/shared/ComingInV1Toast";

export function ProfileSecuritySection() {
  return (
    <section className="flex flex-col gap-3 rounded-md border border-border bg-card/30 p-6">
      <h2 className="text-label text-muted-foreground">
        Security
      </h2>
      <div className="flex items-center justify-between gap-4 py-2">
        <div className="flex flex-col">
          <span className="text-sm font-medium">Password</span>
          <span className="text-xs text-muted-foreground">••••••••</span>
        </div>
        <Button variant="outline" onClick={() => comingInV1("Change password")}>
          Change
        </Button>
      </div>
      <div className="flex items-center justify-between gap-4 border-t border-border py-2 pt-3">
        <div className="flex flex-col">
          <span className="text-sm font-medium">Multi-factor authentication</span>
          <span className="text-xs text-muted-foreground">Enabled (TOTP)</span>
        </div>
        <Button variant="outline" onClick={() => comingInV1("Manage MFA")}>
          Manage
        </Button>
      </div>
    </section>
  );
}
