"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { AlertCircle, Loader2 } from "lucide-react";

import { Modal } from "@/components/shared/Modal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OrgNodePicker } from "@/components/org/OrgNodePicker";
import { useCreateOrgNode } from "@/lib/hooks/use-org-nodes";
import { ApiError } from "@/lib/api/client";
import type { OrgNodeCreatePayload } from "@/lib/api/org-nodes";
import type { OrgNodeTreeItem, OrgNodeType } from "@/types/api";
import {
  ASSIGNABLE_NODE_TYPES,
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

const SELECT_CLASS = cn(FIELD_INPUT_CLASS, "appearance-none");

function FieldLabel({
  htmlFor,
  children,
  required,
}: {
  htmlFor: string;
  children: React.ReactNode;
  required?: boolean;
}) {
  return (
    <label htmlFor={htmlFor} className="text-xs font-medium text-foreground">
      {children}
      {required ? (
        <span className="ml-0.5 text-danger">*</span>
      ) : null}
    </label>
  );
}

export type CreateOrgNodeModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tenantId: string;
  defaultParent: OrgNodeTreeItem | null;
  // Slice 8: parentless (first-node) mode. Hides the parent picker,
  // preselects HQ, and omits parent_id from the POST so the backend
  // resolves the parent to the tenant root. Used by the org page's
  // root-only empty-state CTA.
  parentless?: boolean;
};

export function CreateOrgNodeModal({
  open,
  onOpenChange,
  tenantId,
  defaultParent,
  parentless = false,
}: CreateOrgNodeModalProps) {
  const mutation = useCreateOrgNode(tenantId);
  const [parent, setParent] = useState<OrgNodeTreeItem | null>(defaultParent);
  const [nodeType, setNodeType] = useState<OrgNodeType | "">("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      // The rule is right in general: this resets six pieces of state after the modal has
      // already rendered with the previous entry's values, so there is a frame where a
      // reopened dialog shows what the last one held. The canonical fix is to remount on
      // open with a key prop, which makes the initial useState values the reset and
      // deletes this effect entirely.
      //
      // Not done here because it is a behavioural change to a dialog in a package with no
      // test runner, for a defect nobody has reported seeing. It becomes worth doing when
      // these modals are next touched for a real reason, or when a stale frame is actually
      // observed rather than reasoned about.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setParent(defaultParent);
      // Parentless first node: HQ is the natural first type under the
      // tenant root. Otherwise the user picks after choosing a parent.
      setNodeType(parentless ? "HQ" : "");
      setCode("");
      setName("");
      setFormError(null);
    }
  }, [open, defaultParent, parentless]);

  // In parentless mode the effective parent is the tenant root (ordinal
  // TENANT), so any assignable type above TENANT is allowed.
  const parentOrdinal = parentless
    ? NODE_TYPE_ORDINAL.TENANT
    : parent
      ? NODE_TYPE_ORDINAL[parent.node_type]
      : null;
  const allowedTypes =
    parentOrdinal === null
      ? []
      : ASSIGNABLE_NODE_TYPES.filter(
          (t) => NODE_TYPE_ORDINAL[t] > parentOrdinal,
        );

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    if (!parentless && !parent) {
      setFormError("Pick a parent node.");
      return;
    }
    if (!nodeType) {
      setFormError("Pick a node type.");
      return;
    }
    if (!code || !CODE_REGEX.test(code)) {
      setFormError(
        "Code must be 1-64 chars, alphanumerics and hyphens only, starting and ending with an alphanumeric.",
      );
      return;
    }
    if (!name.trim() || name.trim().length > 200) {
      setFormError("Name is required (1-200 chars).");
      return;
    }

    const payload: OrgNodeCreatePayload = {
      // Parentless: omit parent_id so the backend resolves it to the
      // tenant root (Slice 8). Otherwise send the picked parent.
      ...(parentless ? {} : { parent_id: parent!.id }),
      node_type: nodeType,
      code: code.trim(),
      name: name.trim(),
    };

    try {
      const created = await mutation.mutateAsync(payload);
      toast.success(`${created.name} created`);
      onOpenChange(false);
    } catch (err) {
      if (err instanceof ApiError) {
        setFormError(err.message);
        if (err.status >= 500) {
          toast.error("Could not create node. Please try again.");
        }
        return;
      }
      toast.error("Could not create node. Please try again.");
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Add Org Node"
      subtitle="Add a node under an existing parent. Cascade rule: parent type must sit above the child's."
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
            form="create-org-node-form"
            disabled={mutation.isPending}
          >
            {mutation.isPending ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Creating...
              </>
            ) : (
              "Create node"
            )}
          </Button>
        </div>
      }
    >
      <form
        id="create-org-node-form"
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
              <p className="font-medium">Could not create node.</p>
              <p className="text-muted-foreground">{formError}</p>
            </div>
          </div>
        ) : null}

        {parentless ? (
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="parent">Parent</FieldLabel>
            <p className="text-caption text-foreground-muted">
              First node — it will be added directly under the tenant root.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="parent" required>
              Parent
            </FieldLabel>
            <div className="max-h-56 overflow-auto rounded-md border border-border">
              <OrgNodePicker
                tenantId={tenantId}
                selectedNodeId={parent?.id ?? null}
                onSelect={setParent}
              />
            </div>
            {parent ? (
              <p className="text-caption text-foreground-muted">
                Selected: <span className="font-medium">{parent.name}</span> (
                {NODE_TYPE_LABEL[parent.node_type]})
              </p>
            ) : (
              <p className="text-caption text-foreground-muted">
                Pick a parent from the tree above.
              </p>
            )}
          </div>
        )}

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="node_type" required>
            Node type
          </FieldLabel>
          <select
            id="node_type"
            className={SELECT_CLASS}
            value={nodeType}
            onChange={(e) => setNodeType(e.target.value as OrgNodeType | "")}
            disabled={(!parentless && !parent) || allowedTypes.length === 0}
          >
            <option value="">Select a type…</option>
            {allowedTypes.map((t) => (
              <option key={t} value={t}>
                {NODE_TYPE_LABEL[t]}
              </option>
            ))}
          </select>
          {parent && allowedTypes.length === 0 ? (
            <p className="text-caption text-warning">
              No types can sit below {NODE_TYPE_LABEL[parent.node_type]}; pick a
              higher parent.
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="code" required>
            Code
          </FieldLabel>
          <Input
            id="code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="TX-DAL-01"
            pattern={CODE_PATTERN}
            maxLength={64}
          />
          <p className="text-caption text-foreground-muted">
            1-64 chars. Letters, numbers, hyphens. Must start and end with an
            alphanumeric. Tenant-unique (case-insensitive).
          </p>
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="name" required>
            Name
          </FieldLabel>
          <Input
            id="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Dallas Region — Store 01"
            maxLength={200}
          />
        </div>
      </form>
    </Modal>
  );
}
