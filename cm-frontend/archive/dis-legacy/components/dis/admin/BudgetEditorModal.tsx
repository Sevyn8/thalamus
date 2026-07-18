"use client";

import { useId, useState } from "react";
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
import { useSetBudget } from "@/lib/dis/hooks/use-cost";
import { recordAuditEvent } from "@/lib/dis/audit";
import type { CostFleetRow } from "@/types/dis";

// Phase 5c.8e2: simple Dialog for editing a tenant's monthly LLM
// cost budget. Whole-dollar input (1-9999 range). On save:
// mutation → audit event → close.
//
// Dialog primitive matches BumpVersionModal shape from 5c.8b2 —
// consistent UX vocabulary across "small focused write" surfaces.

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  row: CostFleetRow;
};

export function BudgetEditorModal({ open, onOpenChange, row }: Props) {
  const mutation = useSetBudget();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const inputId = useId();

  // Seed the input from the current budget; "" if no budget set
  // yet (first-set case). Reset whenever the row prop changes.
  const seed = row.monthly_budget_usd ?? "";
  const [seedKey, setSeedKey] = useState(`${row.tenant_id}|${seed}`);
  const [value, setValue] = useState(String(seed));
  const currentSeedKey = `${row.tenant_id}|${seed}`;
  if (seedKey !== currentSeedKey) {
    setSeedKey(currentSeedKey);
    setValue(String(seed));
  }

  const parsed = Number.parseInt(value, 10);
  const isValid =
    Number.isInteger(parsed) && parsed >= 1 && parsed <= 9999;
  const isPending = mutation.isPending;

  async function handleSave(): Promise<void> {
    setSubmitError(null);
    if (!isValid) return;
    try {
      await mutation.mutateAsync({
        tenantId: row.tenant_id,
        input: { monthly_budget_usd: parsed },
      });
      recordAuditEvent({
        event_type: "canonical_dis_cost_budget_set",
        tenant_id: row.tenant_id,
        tenant_name: row.tenant_name,
        prev_budget_usd: row.monthly_budget_usd,
        next_budget_usd: parsed,
      });
      onOpenChange(false);
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Save failed. Try again.",
      );
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Edit budget · {row.tenant_name}</DialogTitle>
          <DialogDescription>
            Monthly USD cap on LLM cost. Set 1-9999, whole dollars.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <label
              htmlFor={inputId}
              className="text-label text-muted-foreground"
            >
              Monthly budget (USD)
            </label>
            <Input
              id={inputId}
              type="number"
              min={1}
              max={9999}
              step={1}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="font-mono"
              placeholder="50"
            />
            {value.length > 0 && !isValid ? (
              <span className="text-caption text-danger">
                Enter a whole-dollar value between 1 and 9999.
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
          <Button onClick={handleSave} disabled={isPending || !isValid}>
            {isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Saving…
              </>
            ) : (
              "Save"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
