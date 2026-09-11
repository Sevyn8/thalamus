"use client";

import { useMemo, useState } from "react";
import { toast } from "sonner";
import { AlertCircle, Loader2 } from "lucide-react";

import { Modal } from "@/components/shared/Modal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTenants } from "@/lib/hooks/use-tenants";
import { useCreateStore } from "@/lib/hooks/use-stores";
import { useOrgTree } from "@/lib/hooks/use-org-nodes";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { ApiError } from "@/lib/api/client";
import type { StoreCreatePayload } from "@/lib/api/stores";
import type { OrgNodeTreeItem, OrgTreeResponse, TaxTreatment } from "@/types/api";
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

type FormState = {
  tenant_id: string;
  parent_org_node_id: string;
  name: string;
  country: string;
  timezone: string;
  currency: string;
  store_code: string;
  tax_treatment: TaxTreatment;
  address: string;
  latitude: string;
  longitude: string;
};

const INITIAL: FormState = {
  tenant_id: "",
  parent_org_node_id: "",
  name: "",
  country: "",
  timezone: "",
  currency: "",
  store_code: "",
  tax_treatment: "EXCLUSIVE",
  address: "",
  latitude: "",
  longitude: "",
};

// The parent picker flattens the tenant's org tree. Valid
// parents are nodes strictly above STORE in the type ordinal
// (TENANT root + BUSINESS_UNIT / HQ / COUNTRY / REGION). Tenant root
// is synthesised from OrgTreeResponse.tenant_root_id (the TENANT-type
// node is excluded from the `tree` array per the schema doc) and
// rendered as the first picker option.
const VALID_PARENT_TYPES = new Set([
  "BUSINESS_UNIT",
  "HQ",
  "COUNTRY",
  "REGION",
]);

type ParentOption = {
  id: string;
  label: string;
  depth: number;
};

function flattenParents(tree: OrgTreeResponse | undefined): ParentOption[] {
  if (!tree) return [];
  const out: ParentOption[] = [
    { id: tree.tenant_root_id, label: tree.tenant_name, depth: 0 },
  ];
  const walk = (
    node: OrgNodeTreeItem,
    parentName: string,
    depth: number,
  ): void => {
    if (VALID_PARENT_TYPES.has(node.node_type)) {
      out.push({
        id: node.id,
        label: `${node.name} (under ${parentName})`,
        depth,
      });
    }
    for (const child of node.children ?? []) {
      walk(child, node.name, depth + 1);
    }
  };
  for (const root of tree.tree) walk(root, tree.tenant_name, 1);
  return out;
}

export type CreateStoreModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: (storeId: string) => void;
};

export function CreateStoreModal({
  open,
  onOpenChange,
  onCreated,
}: CreateStoreModalProps) {
  // TENANT-OWNER persona has exactly one tenant to
  // operate in — auto-bind it from JWT claims and hide the picker.
  // PLATFORM keeps the picker (cross-tenant create) populated from
  // useTenants (which 403s for TENANT JWTs anyway, so the fetch is
  // gated on persona).
  const snapshot = useAuthSnapshot();
  const isTenantPersona = snapshot?.user?.userType === "TENANT";
  const personaTenantId = snapshot?.user?.tenantId ?? "";

  const tenantsQuery = useTenants(undefined, { enabled: !isTenantPersona });
  const mutation = useCreateStore();

  const initialForm = useMemo<FormState>(
    () => ({
      ...INITIAL,
      tenant_id: isTenantPersona ? personaTenantId : "",
    }),
    [isTenantPersona, personaTenantId],
  );

  const [form, setForm] = useState<FormState>(initialForm);
  const [formError, setFormError] = useState<string | null>(null);

  const tenantOptions = tenantsQuery.data?.items ?? [];

  // Load the active tenant's org tree to populate the parent picker.
  // Disabled until a tenant_id is resolved (TENANT persona has one
  // auto-bound; PLATFORM persona waits for the tenant select).
  const orgTreeQuery = useOrgTree(form.tenant_id);
  const parentOptions = useMemo(
    () => flattenParents(orgTreeQuery.data),
    [orgTreeQuery.data],
  );

  function handle<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => {
      // Switching tenant invalidates any previously-picked parent.
      if (key === "tenant_id" && prev.tenant_id !== value) {
        return { ...prev, tenant_id: value as string, parent_org_node_id: "" };
      }
      return { ...prev, [key]: value };
    });
  }

  function reset() {
    setForm(initialForm);
    setFormError(null);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    // Minimal client-side validation: required fields. Backend 422
    // is the safety net for shape errors.
    const required: (keyof FormState)[] = [
      "tenant_id",
      "parent_org_node_id",
      "name",
      "country",
      "timezone",
      "currency",
      "store_code",
      "tax_treatment",
    ];
    for (const key of required) {
      if (!form[key]) {
        setFormError(`${key} is required.`);
        return;
      }
    }

    const payload: StoreCreatePayload = {
      tenant_id: form.tenant_id,
      parent_org_node_id: form.parent_org_node_id,
      name: form.name.trim(),
      country: form.country.trim(),
      timezone: form.timezone.trim(),
      currency: form.currency.trim(),
      store_code: form.store_code.trim(),
      tax_treatment: form.tax_treatment,
    };
    if (form.address.trim()) payload.address = form.address.trim();
    if (form.latitude.trim()) payload.latitude = form.latitude.trim();
    if (form.longitude.trim()) payload.longitude = form.longitude.trim();

    try {
      const created = await mutation.mutateAsync(payload);
      toast.success(`Store ${created.name} created`);
      reset();
      onOpenChange(false);
      onCreated?.(created.id);
    } catch (err) {
      if (err instanceof ApiError) {
        setFormError(err.message);
        if (err.status >= 500) {
          toast.error("Could not create store. Please try again.");
        }
        return;
      }
      toast.error("Could not create store. Please try again.");
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
      size="lg"
      title="Add Store"
      subtitle={
        isTenantPersona ? "Create a new store." : "Create a new store for a tenant."
      }
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
            form="create-store-form"
            disabled={mutation.isPending || !form.parent_org_node_id}
          >
            {mutation.isPending ? (
              <>
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                Creating...
              </>
            ) : (
              "Create store"
            )}
          </Button>
        </div>
      }
    >
      <form
        id="create-store-form"
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
              <p className="font-medium">Could not create store.</p>
              <p className="text-muted-foreground">{formError}</p>
            </div>
          </div>
        ) : null}

        {!isTenantPersona ? (
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="tenant_id" required>
              Tenant
            </FieldLabel>
            <select
              id="tenant_id"
              className={SELECT_CLASS}
              value={form.tenant_id}
              onChange={(e) => handle("tenant_id", e.target.value)}
            >
              <option value="">Select a tenant…</option>
              {tenantOptions.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="parent_org_node_id" required>
            Parent org node
          </FieldLabel>
          <select
            id="parent_org_node_id"
            className={SELECT_CLASS}
            value={form.parent_org_node_id}
            onChange={(e) => handle("parent_org_node_id", e.target.value)}
            disabled={!form.tenant_id || orgTreeQuery.isLoading}
          >
            <option value="">
              {!form.tenant_id
                ? "Select a tenant first…"
                : orgTreeQuery.isLoading
                  ? "Loading org tree…"
                  : "Select a parent…"}
            </option>
            {parentOptions.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {"  ".repeat(opt.depth)}
                {opt.label}
              </option>
            ))}
          </select>
          <p className="text-xs text-muted-foreground">
            The new store is anchored under this node in the org tree.
          </p>
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="name" required>
            Store name
          </FieldLabel>
          <Input
            id="name"
            value={form.name}
            onChange={(e) => handle("name", e.target.value)}
            placeholder="Warsaw Centrum"
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="store_code" required>
              Store code
            </FieldLabel>
            <Input
              id="store_code"
              value={form.store_code}
              onChange={(e) => handle("store_code", e.target.value)}
              placeholder="W-001"
            />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="country" required>
              Country
            </FieldLabel>
            <Input
              id="country"
              value={form.country}
              onChange={(e) => handle("country", e.target.value)}
              placeholder="Poland"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="timezone" required>
              Timezone (IANA)
            </FieldLabel>
            <Input
              id="timezone"
              value={form.timezone}
              onChange={(e) => handle("timezone", e.target.value)}
              placeholder="Europe/Warsaw"
            />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="currency" required>
              Currency (ISO 4217)
            </FieldLabel>
            <Input
              id="currency"
              value={form.currency}
              onChange={(e) => handle("currency", e.target.value.toUpperCase())}
              placeholder="PLN"
              maxLength={3}
            />
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="tax_treatment" required>
            Tax treatment
          </FieldLabel>
          <select
            id="tax_treatment"
            className={SELECT_CLASS}
            value={form.tax_treatment}
            onChange={(e) =>
              handle("tax_treatment", e.target.value as TaxTreatment)
            }
          >
            <option value="EXCLUSIVE">Exclusive</option>
            <option value="INCLUSIVE">Inclusive</option>
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="address">Address</FieldLabel>
          <Input
            id="address"
            value={form.address}
            onChange={(e) => handle("address", e.target.value)}
            placeholder="ul. Marszałkowska 100"
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="latitude">Latitude</FieldLabel>
            <Input
              id="latitude"
              value={form.latitude}
              onChange={(e) => handle("latitude", e.target.value)}
              placeholder="52.2297"
              inputMode="decimal"
            />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="longitude">Longitude</FieldLabel>
            <Input
              id="longitude"
              value={form.longitude}
              onChange={(e) => handle("longitude", e.target.value)}
              placeholder="21.0122"
              inputMode="decimal"
            />
          </div>
        </div>
      </form>
    </Modal>
  );
}
