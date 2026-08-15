"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { AlertCircle, Loader2 } from "lucide-react";

import { Modal } from "@/components/shared/Modal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OrgNodePicker } from "@/components/org/OrgNodePicker";
import { useEditOrgNode } from "@/lib/hooks/use-org-nodes";
import { ApiError } from "@/lib/api/client";
import type { OrgNodePatchPayload } from "@/lib/api/org-nodes";
import type { OrgNodeTreeItem } from "@/types/api";
import {
  CODE_PATTERN,
  CODE_REGEX,
  NODE_TYPE_LABEL,
  NODE_TYPE_ORDINAL,
} from "@/lib/utils/org-node-cascade";
import { cn } from "@/lib/utils";

const FIELD_INPUT_CLASS = cn(
  "h-9 w-full rounded-md border border-input bg-background px-2.5 py-1 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

function FieldLabel({
  htmlFor,
  children,
}: {
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <label htmlFor={htmlFor} className="text-xs font-medium text-foreground">
      {children}
    </label>
  );
}

export type EditOrgNodeModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tenantId: string;
  node: OrgNodeTreeItem;
  // When true, focus is biased toward the parent picker — used by the
  // kebab "Move" entry which folds into this same modal.
  focusReparent?: boolean;
};

export function EditOrgNodeModal({
  open,
  onOpenChange,
  tenantId,
  node,
  focusReparent = false,
}: EditOrgNodeModalProps) {
  const mutation = useEditOrgNode(tenantId);
  const [name, setName] = useState(node.name);
  const [code, setCode] = useState(node.code);
  const [reparentEnabled, setReparentEnabled] = useState(focusReparent);
  const [newParent, setNewParent] = useState<OrgNodeTreeItem | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      // Same shape and same reasoning as CreateOrgNodeModal: the reset runs after the
      // dialog has rendered with the previous node's values, and the canonical fix is a
      // key prop on open so the initial useState values do the work. Deferred for the
      // same reason, that it changes dialog behaviour in a package with no test runner
      // for a frame nobody has reported.
      //
      // Note this one keys on `node` as well as `open`, so it also re-runs when the
      // selected node changes while the dialog stays open. A key on open alone would not
      // cover that; a key of `${open}-${node.id}` would.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setName(node.name);
      setCode(node.code);
      setReparentEnabled(focusReparent);
      setNewParent(null);
      setFormError(null);
    }
  }, [open, node, focusReparent]);

  const nodeOrdinal = NODE_TYPE_ORDINAL[node.node_type];

  function isAllowedAsNewParent(candidate: OrgNodeTreeItem): boolean {
    if (candidate.id === node.id) return false;
    return NODE_TYPE_ORDINAL[candidate.node_type] < nodeOrdinal;
  }

  function buildPatch(): OrgNodePatchPayload {
    const patch: OrgNodePatchPayload = {};
    const trimmedName = name.trim();
    const trimmedCode = code.trim();
    if (trimmedName !== node.name) patch.name = trimmedName;
    if (trimmedCode !== node.code) patch.code = trimmedCode;
    if (reparentEnabled && newParent) patch.parent_id = newParent.id;
    return patch;
  }

  const patch = buildPatch();
  const hasChanges = Object.keys(patch).length > 0;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    if (!hasChanges) {
      setFormError("No fields changed.");
      return;
    }
    if (
      typeof patch.name === "string" &&
      (patch.name.length < 1 || patch.name.length > 200)
    ) {
      setFormError("Name must be 1-200 chars.");
      return;
    }
    if (typeof patch.code === "string" && !CODE_REGEX.test(patch.code)) {
      setFormError(
        "Code must be 1-64 chars, alphanumerics and hyphens only, starting and ending with an alphanumeric.",
      );
      return;
    }
    if (reparentEnabled && !newParent) {
      setFormError("Pick a new parent or disable reparenting.");
      return;
    }
    if (reparentEnabled && newParent && !isAllowedAsNewParent(newParent)) {
      setFormError(
        `${NODE_TYPE_LABEL[newParent.node_type]} cannot be a parent for ${NODE_TYPE_LABEL[node.node_type]}.`,
      );
      return;
    }

    try {
      await mutation.mutateAsync({ nodeId: node.id, patch });
      toast.success(`${node.name} updated`);
      onOpenChange(false);
    } catch (err) {
      if (err instanceof ApiError) {
        setFormError(err.message);
        if (err.status >= 500) {
          toast.error("Could not update node. Please try again.");
        }
        return;
      }
      toast.error("Could not update node. Please try again.");
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Edit Org Node"
      subtitle={`${node.name} (${NODE_TYPE_LABEL[node.node_type]})`}
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={mutation.isPending}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            form="edit-org-node-form"
            disabled={mutation.isPending || !hasChanges}
          >
            {mutation.isPending ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Saving...
              </>
            ) : (
              "Save changes"
            )}
          </Button>
        </div>
      }
    >
      <form
        id="edit-org-node-form"
        onSubmit={onSubmit}
        className="flex flex-col gap-4"
        noValidate
      >
        {formError ? (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-[var(--danger-line)] bg-[var(--danger-bg)] p-3 text-sm dark:bg-danger/5"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
            <div>
              <p className="font-medium">Could not update node.</p>
              <p className="text-muted-foreground">{formError}</p>
            </div>
          </div>
        ) : null}

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="name">Name</FieldLabel>
          <Input
            id="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={200}
            className={FIELD_INPUT_CLASS}
          />
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="code">Code</FieldLabel>
          <Input
            id="code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            pattern={CODE_PATTERN}
            maxLength={64}
            className={FIELD_INPUT_CLASS}
          />
          <p className="text-caption text-foreground-muted">
            Renaming the code rewrites this node&apos;s tree path.
            Tenant-unique (case-insensitive).
          </p>
        </div>

        <div className="flex flex-col gap-2 rounded-md border border-border bg-surface/40 p-3">
          <label className="flex items-center gap-2 text-sm font-medium">
            <input
              type="checkbox"
              checked={reparentEnabled}
              onChange={(e) => setReparentEnabled(e.target.checked)}
            />
            Move this node to a different parent
          </label>
          {reparentEnabled ? (
            <>
              <div className="max-h-56 overflow-auto rounded-md border border-border">
                <OrgNodePicker
                  tenantId={tenantId}
                  selectedNodeId={newParent?.id ?? null}
                  onSelect={setNewParent}
                />
              </div>
              {newParent ? (
                <p className="text-caption text-foreground-muted">
                  New parent:{" "}
                  <span className="font-medium">{newParent.name}</span> (
                  {NODE_TYPE_LABEL[newParent.node_type]})
                  {!isAllowedAsNewParent(newParent) ? (
                    <span className="ml-1 text-warning">
                      — not allowed; pick a node above {NODE_TYPE_LABEL[node.node_type]} in the cascade.
                    </span>
                  ) : null}
                </p>
              ) : (
                <p className="text-caption text-foreground-muted">
                  Pick a new parent from the tree above. The new parent&apos;s
                  type must sit above {NODE_TYPE_LABEL[node.node_type]}.
                </p>
              )}
            </>
          ) : null}
        </div>
      </form>
    </Modal>
  );
}
