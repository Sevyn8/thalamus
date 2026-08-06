"use client";

import { useState } from "react";
import { toast } from "sonner";
import { AlertCircle, Loader2 } from "lucide-react";

import { Modal } from "@/components/shared/Modal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useUpdateStore } from "@/lib/hooks/use-stores";
import { ApiError } from "@/lib/api/client";
import type { StorePatchPayload } from "@/lib/api/stores";
import type { StoreDetail, TaxTreatment } from "@/types/api";
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

type FormState = {
  name: string;
  store_code: string;
  country: string;
  timezone: string;
  currency: string;
  tax_treatment: TaxTreatment;
  address: string;
  latitude: string;
  longitude: string;
};

function fromStore(store: StoreDetail): FormState {
  return {
    name: store.name,
    store_code: store.store_code ?? "",
    country: store.country,
    timezone: store.timezone,
    currency: store.currency,
    tax_treatment: store.tax_treatment,
    address: store.address ?? "",
    latitude: store.latitude ?? "",
    longitude: store.longitude ?? "",
  };
}

export type EditStoreModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  store: StoreDetail;
};

export function EditStoreModal({
  open,
  onOpenChange,
  store,
}: EditStoreModalProps) {
  const mutation = useUpdateStore();
  const [form, setForm] = useState<FormState>(() => fromStore(store));
  const [formError, setFormError] = useState<string | null>(null);

  function handle<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function reset() {
    setForm(fromStore(store));
    setFormError(null);
  }

  // Build the patch payload by only including fields that changed
  // from the original. Backend raises EmptyPatchError (422) if no
  // field was modified.
  function buildPatch(): StorePatchPayload {
    const patch: StorePatchPayload = {};
    if (form.name !== store.name) patch.name = form.name.trim();
    if (form.store_code !== (store.store_code ?? "")) {
      patch.store_code = form.store_code.trim() || null;
    }
    if (form.country !== store.country) patch.country = form.country.trim();
    if (form.timezone !== store.timezone) patch.timezone = form.timezone.trim();
    if (form.currency !== store.currency) patch.currency = form.currency.trim();
    if (form.tax_treatment !== store.tax_treatment) {
      patch.tax_treatment = form.tax_treatment;
    }
    if (form.address !== (store.address ?? "")) {
      patch.address = form.address.trim() || null;
    }
    if (form.latitude !== (store.latitude ?? "")) {
      patch.latitude = form.latitude.trim() || null;
    }
    if (form.longitude !== (store.longitude ?? "")) {
      patch.longitude = form.longitude.trim() || null;
    }
    return patch;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    const patch = buildPatch();
    if (Object.keys(patch).length === 0) {
      setFormError("No fields changed.");
      return;
    }
    try {
      await mutation.mutateAsync({ id: store.id, patch });
      toast.success(`Store ${store.name} updated`);
      onOpenChange(false);
    } catch (err) {
      if (err instanceof ApiError) {
        setFormError(err.message);
        if (err.status >= 500) {
          toast.error("Could not update store. Please try again.");
        }
        return;
      }
      toast.error("Could not update store. Please try again.");
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
      title="Edit Store"
      subtitle={store.name}
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
            form="edit-store-form"
            disabled={mutation.isPending}
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
        id="edit-store-form"
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
              <p className="font-medium">Could not update store.</p>
              <p className="text-muted-foreground">{formError}</p>
            </div>
          </div>
        ) : null}

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="name">Store name</FieldLabel>
          <Input
            id="name"
            value={form.name}
            onChange={(e) => handle("name", e.target.value)}
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="store_code">Store code</FieldLabel>
            <Input
              id="store_code"
              value={form.store_code}
              onChange={(e) => handle("store_code", e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="country">Country</FieldLabel>
            <Input
              id="country"
              value={form.country}
              onChange={(e) => handle("country", e.target.value)}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="timezone">Timezone (IANA)</FieldLabel>
            <Input
              id="timezone"
              value={form.timezone}
              onChange={(e) => handle("timezone", e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="currency">Currency (ISO 4217)</FieldLabel>
            <Input
              id="currency"
              value={form.currency}
              onChange={(e) => handle("currency", e.target.value.toUpperCase())}
              maxLength={3}
            />
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="tax_treatment">Tax treatment</FieldLabel>
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
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="latitude">Latitude</FieldLabel>
            <Input
              id="latitude"
              value={form.latitude}
              onChange={(e) => handle("latitude", e.target.value)}
              inputMode="decimal"
            />
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="longitude">Longitude</FieldLabel>
            <Input
              id="longitude"
              value={form.longitude}
              onChange={(e) => handle("longitude", e.target.value)}
              inputMode="decimal"
            />
          </div>
        </div>
      </form>
    </Modal>
  );
}
