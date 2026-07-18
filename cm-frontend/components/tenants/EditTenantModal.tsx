"use client";

import { useState } from "react";
import { toast } from "sonner";
import { AlertCircle, Loader2 } from "lucide-react";

import { Modal } from "@/components/shared/Modal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLookups } from "@/lib/hooks/use-lookups";
import { useEditTenant } from "@/lib/hooks/use-tenants";
import { ApiError } from "@/lib/api/client";
import type { TenantPatchPayload } from "@/lib/api/tenants";
import type {
  TenantDetail,
  TenantIndustry,
  TenantTier,
} from "@/types/api";
import { cn } from "@/lib/utils";

// Phase 5n.5a (2026-05-18): EditTenantModal mirrors EditStoreModal's
// shape. Diff-based PATCH (backend raises 422 EmptyPatchError on no
// changes; we disable Save when diff is empty to fail-fast in the
// UI). Server-wait pattern, no optimistic state. Permission gate
// (canEditTenant on ADMIN.TENANTS.CONFIGURE.GLOBAL) lives in the
// drawer; this modal trusts the drawer.

const FIELD_INPUT_CLASS = cn(
  "h-9 w-full rounded-md border border-input bg-background px-2.5 py-1 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

const SELECT_CLASS = cn(FIELD_INPUT_CLASS, "appearance-none");

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

// Form state matches the TenantPatchRequest schema's patchable subset
// (region / status / id / *_at omitted — those are not patchable
// per backend's `extra="forbid"` on TenantPatchRequest).
type FormState = {
  name: string;
  display_code: string;
  country: string;
  tier: TenantTier | "";
  industry: TenantIndustry | "";
  primary_contact_name: string;
  contact_email: string;
  number_of_stores: string;
  number_of_stores_as_of_date: string;
  monthly_revenue_usd: string;
  monthly_revenue_as_of_date: string;
};

function fromTenant(t: TenantDetail): FormState {
  return {
    name: t.name,
    display_code: t.display_code ?? "",
    country: t.country ?? "",
    tier: t.tier ?? "",
    industry: t.industry ?? "",
    primary_contact_name: t.primary_contact_name ?? "",
    contact_email: t.contact_email ?? "",
    number_of_stores:
      t.number_of_stores !== null ? String(t.number_of_stores) : "",
    number_of_stores_as_of_date: t.number_of_stores_as_of_date ?? "",
    monthly_revenue_usd: t.monthly_revenue_usd ?? "",
    monthly_revenue_as_of_date: t.monthly_revenue_as_of_date ?? "",
  };
}

export type EditTenantModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tenant: TenantDetail;
};

export function EditTenantModal({
  open,
  onOpenChange,
  tenant,
}: EditTenantModalProps) {
  const lookups = useLookups();
  const mutation = useEditTenant();
  const [form, setForm] = useState<FormState>(() => fromTenant(tenant));
  const [formError, setFormError] = useState<string | null>(null);

  const tiers = lookups.data?.tenant_tiers ?? [];
  const industries = lookups.data?.tenant_industries ?? [];

  function handle<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function reset() {
    setForm(fromTenant(tenant));
    setFormError(null);
  }

  // Build the patch by including only fields that changed from the
  // tenant's current values. Empty strings on optional nullable
  // fields become explicit null on the wire (clears the value);
  // unchanged fields are omitted entirely (exclude_unset on backend).
  function buildPatch(): TenantPatchPayload {
    const patch: TenantPatchPayload = {};
    const original = fromTenant(tenant);

    if (form.name !== original.name) {
      patch.name = form.name.trim();
    }
    if (form.display_code !== original.display_code) {
      patch.display_code = form.display_code.trim() || null;
    }
    if (form.country !== original.country) {
      patch.country = form.country.trim() || null;
    }
    if (form.tier !== original.tier) {
      patch.tier = (form.tier || null) as TenantTier | null;
    }
    if (form.industry !== original.industry) {
      patch.industry = (form.industry || null) as TenantIndustry | null;
    }
    if (form.primary_contact_name !== original.primary_contact_name) {
      patch.primary_contact_name = form.primary_contact_name.trim() || null;
    }
    if (form.contact_email !== original.contact_email) {
      patch.contact_email =
        form.contact_email.trim().toLowerCase() || null;
    }
    if (form.number_of_stores !== original.number_of_stores) {
      const n = Number(form.number_of_stores);
      patch.number_of_stores = Number.isFinite(n) ? n : null;
    }
    if (form.number_of_stores_as_of_date !== original.number_of_stores_as_of_date) {
      patch.number_of_stores_as_of_date =
        form.number_of_stores_as_of_date || null;
    }
    if (form.monthly_revenue_usd !== original.monthly_revenue_usd) {
      patch.monthly_revenue_usd = form.monthly_revenue_usd.trim() || null;
    }
    if (form.monthly_revenue_as_of_date !== original.monthly_revenue_as_of_date) {
      patch.monthly_revenue_as_of_date =
        form.monthly_revenue_as_of_date || null;
    }

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
    try {
      await mutation.mutateAsync({ id: tenant.id, patch });
      toast.success(`Tenant ${tenant.name} updated`);
      onOpenChange(false);
    } catch (err) {
      if (err instanceof ApiError) {
        setFormError(err.message);
        if (err.status >= 500) {
          toast.error("Could not update tenant. Please try again.");
        }
        return;
      }
      toast.error("Could not update tenant. Please try again.");
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
      title="Edit Tenant"
      subtitle={tenant.name}
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
            form="edit-tenant-form"
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
        id="edit-tenant-form"
        onSubmit={onSubmit}
        className="flex flex-col gap-4"
        noValidate
      >
        {formError ? (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm dark:border-red-500/30 dark:bg-red-500/5"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />
            <div>
              <p className="font-medium">Could not update tenant.</p>
              <p className="text-muted-foreground">{formError}</p>
            </div>
          </div>
        ) : null}

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="name">Tenant name</FieldLabel>
          <Input
            id="name"
            value={form.name}
            onChange={(e) => handle("name", e.target.value)}
          />
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="display_code">Display code</FieldLabel>
          <Input
            id="display_code"
            value={form.display_code}
            onChange={(e) => handle("display_code", e.target.value)}
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="tier">Tier</FieldLabel>
            <select
              id="tier"
              className={SELECT_CLASS}
              value={form.tier}
              onChange={(e) => handle("tier", e.target.value as TenantTier)}
            >
              <option value="">—</option>
              {tiers.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.display_name}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="industry">Industry</FieldLabel>
            <select
              id="industry"
              className={SELECT_CLASS}
              value={form.industry}
              onChange={(e) =>
                handle("industry", e.target.value as TenantIndustry)
              }
            >
              <option value="">—</option>
              {industries.map((i) => (
                <option key={i.code} value={i.code}>
                  {i.display_name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="country">Country</FieldLabel>
          <Input
            id="country"
            value={form.country}
            onChange={(e) => handle("country", e.target.value)}
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="primary_contact_name">
              Primary contact
            </FieldLabel>
            <Input
              id="primary_contact_name"
              value={form.primary_contact_name}
              onChange={(e) =>
                handle("primary_contact_name", e.target.value)
              }
            />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="contact_email">Contact email</FieldLabel>
            <Input
              id="contact_email"
              type="email"
              value={form.contact_email}
              onChange={(e) => handle("contact_email", e.target.value)}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="number_of_stores">Stores</FieldLabel>
            <Input
              id="number_of_stores"
              type="number"
              inputMode="numeric"
              min={1}
              value={form.number_of_stores}
              onChange={(e) => handle("number_of_stores", e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="number_of_stores_as_of_date">
              Stores as-of date
            </FieldLabel>
            <Input
              id="number_of_stores_as_of_date"
              type="date"
              value={form.number_of_stores_as_of_date}
              onChange={(e) =>
                handle("number_of_stores_as_of_date", e.target.value)
              }
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="monthly_revenue_usd">
              Monthly revenue (USD)
            </FieldLabel>
            <Input
              id="monthly_revenue_usd"
              inputMode="decimal"
              value={form.monthly_revenue_usd}
              onChange={(e) =>
                handle("monthly_revenue_usd", e.target.value)
              }
              placeholder="500.00"
            />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="monthly_revenue_as_of_date">
              Revenue as-of date
            </FieldLabel>
            <Input
              id="monthly_revenue_as_of_date"
              type="date"
              value={form.monthly_revenue_as_of_date}
              onChange={(e) =>
                handle("monthly_revenue_as_of_date", e.target.value)
              }
            />
          </div>
        </div>
      </form>
    </Modal>
  );
}
