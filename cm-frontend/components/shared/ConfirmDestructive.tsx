"use client";

import { useId, useState, type ReactNode } from "react";
import { Loader2 } from "lucide-react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export type ConfirmDestructiveProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  // String the user must type. Trimmed both sides; case-sensitive match.
  confirmText: string;
  // Confirm button label, e.g., "Terminate tenant".
  confirmLabel: string;
  cancelLabel?: string;
  // Defaults to true (red destructive button). Set false for non-destructive
  // type-to-confirm flows (rare).
  destructive?: boolean;
  onConfirm: () => void | Promise<void>;
};

export function ConfirmDestructive({
  open,
  onOpenChange,
  title,
  description,
  confirmText,
  confirmLabel,
  cancelLabel = "Cancel",
  destructive = true,
  onConfirm,
}: ConfirmDestructiveProps) {
  const inputId = useId();
  const [typed, setTyped] = useState("");
  const [pending, setPending] = useState(false);

  const matches = typed.trim() === confirmText;

  // Reset on close path so re-open starts blank. Avoids set-state-in-effect.
  function handleOpenChange(next: boolean) {
    if (!next) {
      setTyped("");
      setPending(false);
    }
    onOpenChange(next);
  }

  async function handleConfirm() {
    if (!matches || pending) return;
    try {
      setPending(true);
      await onConfirm();
      handleOpenChange(false);
    } finally {
      setPending(false);
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={handleOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>

        <div className="flex flex-col gap-2">
          <label htmlFor={inputId} className="text-label text-foreground-muted">
            Type <code className="text-foreground">{confirmText}</code> to confirm
          </label>
          <Input
            id={inputId}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            disabled={pending}
            autoComplete="off"
            spellCheck={false}
            placeholder={confirmText}
          />
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{cancelLabel}</AlertDialogCancel>
          <AlertDialogAction
            variant={destructive ? "destructive" : "default"}
            disabled={!matches || pending}
            onClick={() => void handleConfirm()}
            className={cn(pending && "cursor-progress")}
          >
            {pending ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Working...
              </>
            ) : (
              confirmLabel
            )}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
