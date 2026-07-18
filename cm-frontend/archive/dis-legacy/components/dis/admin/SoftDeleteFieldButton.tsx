"use client";

import { useState } from "react";
import { Trash2, Undo2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ConfirmDestructive } from "@/components/shared/ConfirmDestructive";
import { useUpdateCanonicalField } from "@/lib/dis/hooks/use-canonical-schema";
import { recordAuditEvent } from "@/lib/dis/audit";
import type { CanonicalSchemaField } from "@/types/dis";

// Phase 5d.6: soft-delete + restore for canonical fields.
//
// Soft-delete is logical only — no cascading. ColumnMappings,
// ValidationRules, and Templates that reference this field via
// canonical_field_id continue to function because the field row
// still exists in the data; it's just filtered from default
// presentation. Restore returns visibility. Architectural rationale
// in BUILD_PLAN 5d.6 closeout.
//
// Delete confirm-text is the field's name (case-sensitive). Mirrors
// the Tenant CREATE / SUSPEND / TERMINATE confirm pattern from
// 5c.8d2 / 5c.8d3. Restore is a simple one-click action (no
// confirm — restore is reversible).

export function SoftDeleteFieldButton({
  field,
  domainId,
}: {
  field: CanonicalSchemaField;
  domainId: string;
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const update = useUpdateCanonicalField();

  async function onConfirm() {
    try {
      await update.mutateAsync({
        domainId,
        fieldId: field.id,
        input: { deleted_at: new Date().toISOString() },
      });
      recordAuditEvent({
        event_type: "canonical_schema_field_soft_deleted",
        domain_id: domainId,
        field_id: field.id,
        field_name: field.name,
        classification: "breaking",
      });
      toast.success(`Deleted ${field.name}`);
      setConfirmOpen(false);
    } catch {
      toast.error("Could not delete field");
    }
  }

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setConfirmOpen(true)}
        aria-label={`Delete ${field.display_name ?? field.name}`}
      >
        <Trash2 className="h-3.5 w-3.5 text-destructive" />
        Delete
      </Button>
      <ConfirmDestructive
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={`Delete canonical field "${field.name}"`}
        description={
          <>
            This soft-deletes the field. Templates, sources, and validation
            rules referencing it continue to function — the field is hidden
            from default views but its data is preserved and can be restored.
            Type{" "}
            <span className="font-mono text-foreground">{field.name}</span>{" "}
            to confirm.
          </>
        }
        confirmText={field.name}
        confirmLabel="Delete field"
        onConfirm={onConfirm}
      />
    </>
  );
}

export function RestoreFieldButton({
  field,
  domainId,
}: {
  field: CanonicalSchemaField;
  domainId: string;
}) {
  const update = useUpdateCanonicalField();

  async function onClick() {
    try {
      await update.mutateAsync({
        domainId,
        fieldId: field.id,
        input: { deleted_at: null },
      });
      recordAuditEvent({
        event_type: "canonical_schema_field_restored",
        domain_id: domainId,
        field_id: field.id,
        field_name: field.name,
      });
      toast.success(`Restored ${field.name}`);
    } catch {
      toast.error("Could not restore field");
    }
  }

  return (
    <Button
      variant="outline"
      size="sm"
      onClick={onClick}
      aria-label={`Restore ${field.display_name ?? field.name}`}
    >
      <Undo2 className="h-3.5 w-3.5" />
      Restore
    </Button>
  );
}
