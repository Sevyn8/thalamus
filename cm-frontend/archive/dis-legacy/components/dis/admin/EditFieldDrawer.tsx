"use client";

import { useId, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorInline } from "@/components/shared/ErrorInline";
import {
  useAddCanonicalField,
  useUpdateCanonicalField,
} from "@/lib/dis/hooks/use-canonical-schema";
import {
  classifyChange,
  type ClassificationResult,
} from "@/lib/dis/canonical-schema-classifier";
import { recordAuditEvent } from "@/lib/dis/audit";
import type {
  CanonicalSchemaField,
  CanonicalSchemaFieldType,
} from "@/types/dis";
import type { CanonicalSchemaFieldUpdateInput } from "@/lib/dis/api/canonical-schema";

// Phase 5c.8b1: Anjali edits a canonical-field's properties. Drawer
// holds full editable property set (display_name / description /
// type / required / nullable / unique / business_owner /
// example_values / constraints / synonyms / pii). Live classifier
// banner re-runs on each change. referenced_by warning shown when
// field has > 0 downstream consumers (informational, doesn't block).
//
// INTENTIONAL: name (field_id) is NOT editable in edit mode. Field
// IDs are stable wire-codes that downstream consumers (templates,
// sources, validation rules) reference. Renaming would silently
// break those consumers. Only display_name is editable.
//
// Phase 5c.8b2: drawer extends to dual-mode (mode: "add" | "edit").
// In add mode: id + name editable+required, classifier banner
// replaced with static "New field — additive impact" message,
// minimal field set per Trim A (id / name / type / description /
// required / nullable / pii). After successful add, parent flips
// state to mode: "edit" on the just-created field — Anjali can
// immediately enrich with synonyms / examples / constraints /
// business_owner without re-navigating.

type EditModeProps = {
  mode: "edit";
  open: boolean;
  onOpenChange: (open: boolean) => void;
  domainId: string;
  field: CanonicalSchemaField;
  existingFieldIds?: never;
  onCreated?: never;
};

type AddModeProps = {
  mode: "add";
  open: boolean;
  onOpenChange: (open: boolean) => void;
  domainId: string;
  field?: never;
  existingFieldIds: string[];
  onCreated: (field: CanonicalSchemaField) => void;
};

type Props = EditModeProps | AddModeProps;

const TYPE_OPTIONS: CanonicalSchemaFieldType[] = [
  "string",
  "number",
  "datetime",
  "boolean",
  "enum",
];

function snakeCase(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_");
}

export function EditFieldDrawer(props: Props) {
  if (props.mode === "add") {
    return <AddFieldDrawerInner {...props} />;
  }
  return <EditFieldDrawerInner {...props} />;
}

function EditFieldDrawerInner({
  open,
  onOpenChange,
  domainId,
  field,
}: EditModeProps) {
  const updateMutation = useUpdateCanonicalField();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [draft, setDraft] = useState<CanonicalSchemaFieldUpdateInput>(() => ({
    display_name: field.display_name ?? field.name,
    description: field.description,
    type: field.type,
    required: field.required ?? false,
    nullable: field.nullable ?? true,
    unique: field.unique ?? false,
    business_owner: field.business_owner ?? "",
    example_values: field.example_values ?? [],
    constraints: field.constraints ?? [],
    synonyms: field.synonyms,
    pii: field.pii,
  }));

  const classification: ClassificationResult = useMemo(
    () => classifyChange(field, draft),
    [field, draft],
  );

  const refCount = field.referenced_by ?? 0;
  const isPending = updateMutation.isPending;
  const displayNameId = useId();
  const descriptionId = useId();
  const typeId = useId();
  const businessOwnerId = useId();
  const exampleValuesId = useId();
  const constraintsId = useId();
  const synonymsId = useId();

  function update<K extends keyof CanonicalSchemaFieldUpdateInput>(
    key: K,
    value: CanonicalSchemaFieldUpdateInput[K],
  ): void {
    setDraft((prev) => ({ ...prev, [key]: value }));
  }

  function setLines(
    key: "example_values" | "constraints" | "synonyms",
    raw: string,
  ): void {
    const lines = raw
      .split("\n")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    update(key, lines);
  }

  async function handleSave(): Promise<void> {
    setSubmitError(null);
    try {
      const changes: Record<string, { before: unknown; after: unknown }> = {};
      const draftRecord = draft as Record<string, unknown>;
      const fieldRecord = field as unknown as Record<string, unknown>;
      for (const key of Object.keys(draftRecord)) {
        const before = fieldRecord[key];
        const after = draftRecord[key];
        if (JSON.stringify(before) !== JSON.stringify(after)) {
          changes[key] = { before, after };
        }
      }
      await updateMutation.mutateAsync({
        domainId,
        fieldId: field.id,
        input: draft,
      });
      recordAuditEvent({
        event_type: "canonical_schema_edit",
        domain_id: domainId,
        field_id: field.id,
        classification: classification.kind,
        reasons: classification.reasons,
        changes,
      });
      onOpenChange(false);
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Save failed. Try again.",
      );
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex flex-col gap-4 sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Edit canonical field</SheetTitle>
          <SheetDescription>
            <span className="font-mono text-xs text-muted-foreground">
              {field.id}
            </span>
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-4">
          {refCount > 0 ? (
            <div className="flex flex-col gap-1 rounded-md border border-amber-200 bg-amber-50 p-3 text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
              <span className="text-label">Referenced by</span>
              <p className="text-sm">
                This field is referenced by {refCount} downstream consumer
                {refCount === 1 ? "" : "s"} (templates / sources / validation
                rules). Edits may break consumers.
              </p>
            </div>
          ) : null}

          <ClassificationBanner result={classification} />

          <div className="flex flex-col gap-2">
            <label htmlFor={displayNameId} className="text-label text-muted-foreground">
              Display name
            </label>
            <Input
              id={displayNameId}
              value={draft.display_name ?? ""}
              onChange={(e) => update("display_name", e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-2">
            <label htmlFor={descriptionId} className="text-label text-muted-foreground">
              Description
            </label>
            <textarea
              id={descriptionId}
              rows={3}
              value={draft.description ?? ""}
              onChange={(e) => update("description", e.target.value)}
              className="rounded-md border border-input bg-background px-2.5 py-1.5 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none dark:bg-input/30"
            />
          </div>

          <div className="flex flex-col gap-2">
            <label htmlFor={typeId} className="text-label text-muted-foreground">
              Type
            </label>
            <select
              id={typeId}
              value={draft.type}
              onChange={(e) =>
                update("type", e.target.value as CanonicalSchemaFieldType)
              }
              className="h-9 rounded-md border border-input bg-background px-2.5 py-1 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none dark:bg-input/30"
            >
              {TYPE_OPTIONS.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <CheckboxRow
              label="Required"
              checked={!!draft.required}
              onChange={(v) => update("required", v)}
            />
            <CheckboxRow
              label="Nullable"
              checked={!!draft.nullable}
              onChange={(v) => update("nullable", v)}
            />
            <CheckboxRow
              label="Unique"
              checked={!!draft.unique}
              onChange={(v) => update("unique", v)}
            />
            <CheckboxRow
              label="PII"
              checked={!!draft.pii}
              onChange={(v) => update("pii", v)}
            />
          </div>

          <div className="flex flex-col gap-2">
            <label
              htmlFor={businessOwnerId}
              className="text-label text-muted-foreground"
            >
              Business owner
            </label>
            <Input
              id={businessOwnerId}
              value={draft.business_owner ?? ""}
              onChange={(e) => update("business_owner", e.target.value)}
            />
          </div>

          <div className="flex flex-col gap-2">
            <label
              htmlFor={exampleValuesId}
              className="text-label text-muted-foreground"
            >
              Example values (one per line)
            </label>
            <textarea
              id={exampleValuesId}
              rows={3}
              defaultValue={(draft.example_values ?? []).join("\n")}
              onBlur={(e) => setLines("example_values", e.target.value)}
              className="rounded-md border border-input bg-background px-2.5 py-1.5 text-sm font-mono focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none dark:bg-input/30"
            />
          </div>

          <div className="flex flex-col gap-2">
            <label
              htmlFor={constraintsId}
              className="text-label text-muted-foreground"
            >
              Constraints (one per line)
            </label>
            <textarea
              id={constraintsId}
              rows={3}
              defaultValue={(draft.constraints ?? []).join("\n")}
              onBlur={(e) => setLines("constraints", e.target.value)}
              className="rounded-md border border-input bg-background px-2.5 py-1.5 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none dark:bg-input/30"
            />
          </div>

          <div className="flex flex-col gap-2">
            <label htmlFor={synonymsId} className="text-label text-muted-foreground">
              Synonyms (one per line)
            </label>
            <textarea
              id={synonymsId}
              rows={3}
              defaultValue={(draft.synonyms ?? []).join("\n")}
              onBlur={(e) => setLines("synonyms", e.target.value)}
              className="rounded-md border border-input bg-background px-2.5 py-1.5 text-sm font-mono focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none dark:bg-input/30"
            />
          </div>

          {submitError ? <ErrorInline message={submitError} /> : null}
        </div>

        <SheetFooter className="border-t border-border">
          <Button
            variant="ghost"
            disabled={isPending}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={isPending}>
            {isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Saving…
              </>
            ) : (
              "Save"
            )}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

// Phase 5c.8b2: parallel inner component for add mode. Kept inline
// (vs separate file) to avoid drift on the shared form-row markup;
// the two inner components share the CheckboxRow + ClassificationBanner
// helpers below. Trim A keeps the add form minimal: id / name / type /
// description / required / nullable / pii. Synonyms / examples /
// constraints / business_owner are filled via Edit immediately after
// the field is created (path a — parent flips mode to edit on
// onCreated callback).
function AddFieldDrawerInner({
  open,
  onOpenChange,
  domainId,
  existingFieldIds,
  onCreated,
}: AddModeProps) {
  const addMutation = useAddCanonicalField();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [fieldId, setFieldId] = useState("");
  const [fieldIdManuallyEdited, setFieldIdManuallyEdited] = useState(false);
  const [type, setType] = useState<CanonicalSchemaFieldType>("string");
  const [description, setDescription] = useState("");
  const [required, setRequired] = useState(false);
  const [nullable, setNullable] = useState(true);
  const [pii, setPii] = useState(false);

  const idInputId = useId();
  const nameInputId = useId();
  const typeInputId = useId();
  const descInputId = useId();

  // Auto-suggest id when name changes — unless Anjali has manually
  // edited the id field, in which case her override wins.
  function handleNameChange(next: string): void {
    setName(next);
    if (!fieldIdManuallyEdited) {
      const slug = snakeCase(next);
      setFieldId(slug ? `${domainId}.${slug}` : "");
    }
  }

  const isPrefixOk = !fieldId || fieldId.startsWith(`${domainId}.`);
  const isUnique = !existingFieldIds.includes(fieldId);
  const isFormValid =
    name.trim().length > 0 &&
    fieldId.trim().length > 0 &&
    isPrefixOk &&
    isUnique;

  const isPending = addMutation.isPending;

  async function handleSave(): Promise<void> {
    setSubmitError(null);
    if (!isFormValid) return;
    try {
      const created = await addMutation.mutateAsync({
        domainId,
        input: {
          id: fieldId,
          name,
          type,
          description,
          required,
          nullable,
          pii,
        },
      });
      recordAuditEvent({
        event_type: "canonical_schema_field_added",
        domain_id: domainId,
        field_id: created.id,
        field_name: created.name,
      });
      onCreated(created);
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Save failed. Try again.",
      );
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex flex-col gap-4 sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>Add canonical field</SheetTitle>
          <SheetDescription>
            New fields are additive — they don&apos;t affect existing
            data parsing.
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-4">
          <div className="flex flex-col gap-1 rounded-md border border-blue-200 bg-blue-50 p-3 text-blue-900 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-200">
            <span className="text-label">New field — additive impact</span>
            <p className="text-sm">
              Add the minimum metadata now. You can enrich with synonyms,
              examples, constraints, and business owner immediately after
              creation.
            </p>
          </div>

          <div className="flex flex-col gap-2">
            <label htmlFor={nameInputId} className="text-label text-muted-foreground">
              Name
            </label>
            <Input
              id={nameInputId}
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder="e.g. Bonus payout"
            />
          </div>

          <div className="flex flex-col gap-2">
            <label htmlFor={idInputId} className="text-label text-muted-foreground">
              Field ID
            </label>
            <Input
              id={idInputId}
              value={fieldId}
              onChange={(e) => {
                setFieldId(e.target.value);
                setFieldIdManuallyEdited(true);
              }}
              placeholder={`${domainId}.bonus_payout`}
              className="font-mono"
            />
            {fieldId && !isPrefixOk ? (
              <span className="text-caption text-danger">
                Must start with &quot;{domainId}.&quot;.
              </span>
            ) : null}
            {fieldId && !isUnique ? (
              <span className="text-caption text-danger">
                A field with this id already exists in this domain.
              </span>
            ) : null}
          </div>

          <div className="flex flex-col gap-2">
            <label htmlFor={typeInputId} className="text-label text-muted-foreground">
              Type
            </label>
            <select
              id={typeInputId}
              value={type}
              onChange={(e) => setType(e.target.value as CanonicalSchemaFieldType)}
              className="h-9 rounded-md border border-input bg-background px-2.5 py-1 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none dark:bg-input/30"
            >
              {TYPE_OPTIONS.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-2">
            <label htmlFor={descInputId} className="text-label text-muted-foreground">
              Description
            </label>
            <textarea
              id={descInputId}
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="rounded-md border border-input bg-background px-2.5 py-1.5 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none dark:bg-input/30"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <CheckboxRow
              label="Required"
              checked={required}
              onChange={setRequired}
            />
            <CheckboxRow
              label="Nullable"
              checked={nullable}
              onChange={setNullable}
            />
            <CheckboxRow label="PII" checked={pii} onChange={setPii} />
          </div>

          {submitError ? <ErrorInline message={submitError} /> : null}
        </div>

        <SheetFooter className="border-t border-border">
          <Button
            variant="ghost"
            disabled={isPending}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={isPending || !isFormValid}>
            {isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Creating…
              </>
            ) : (
              "Create field"
            )}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function CheckboxRow({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="flex items-center gap-2 text-sm">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-input"
      />
      {label}
    </label>
  );
}

function ClassificationBanner({ result }: { result: ClassificationResult }) {
  const tone =
    result.kind === "breaking"
      ? "border-red-200 bg-red-50 text-red-900 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-200"
      : result.kind === "additive"
        ? "border-blue-200 bg-blue-50 text-blue-900 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-200"
        : "border-border bg-card/50 text-muted-foreground";
  const label =
    result.kind === "breaking"
      ? "Breaking change"
      : result.kind === "additive"
        ? "Additive change"
        : "Neutral";
  return (
    <div className={`flex flex-col gap-1 rounded-md border p-3 ${tone}`}>
      <span className="text-label">{label}</span>
      <ul className="flex flex-col gap-0.5">
        {result.reasons.map((r) => (
          <li key={r} className="text-sm">
            · {r}
          </li>
        ))}
      </ul>
    </div>
  );
}
