"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Controller, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { AlertCircle, Loader2 } from "lucide-react";

import { Modal } from "@/components/shared/Modal";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLookups } from "@/lib/hooks/use-lookups";
import { useProvisionTenant } from "@/lib/hooks/use-provision-tenant";
import { ApiError } from "@/lib/api/client";
import {
  provisionTenantSchema,
  type ProvisionTenantInput,
} from "@/lib/schemas/provision-tenant";
import { cn } from "@/lib/utils";

type ProvisionTenantModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

const FIELD_INPUT_CLASS = cn(
  "h-9 w-full rounded-md border border-input bg-background px-2.5 py-1 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

const SELECT_CLASS = cn(FIELD_INPUT_CLASS, "appearance-none");

function FieldLabel({ htmlFor, children, required }: { htmlFor: string; children: React.ReactNode; required?: boolean }) {
  return (
    <label htmlFor={htmlFor} className="text-xs font-medium text-foreground">
      {children}
      {required ? <span className="ml-0.5 text-red-600 dark:text-red-400">*</span> : null}
    </label>
  );
}

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="mt-1 text-xs text-red-600 dark:text-red-400">{message}</p>;
}

const DEFAULT_VALUES: ProvisionTenantInput = {
  name: "",
  display_code: "",
  region: "US",
  tier: "SMB",
  industry: "CONVENIENCE",
  country: "",
  primary_contact_name: "",
  contact_email: "",
  number_of_stores: 1,
  monthly_revenue_usd: "",
};

export function ProvisionTenantModal({ open, onOpenChange }: ProvisionTenantModalProps) {
  const router = useRouter();
  const lookups = useLookups();
  const mutation = useProvisionTenant();
  const [formError, setFormError] = useState<string | null>(null);
  const [confirmDiscardOpen, setConfirmDiscardOpen] = useState(false);

  const form = useForm<ProvisionTenantInput>({
    resolver: zodResolver(provisionTenantSchema),
    mode: "onBlur",
    defaultValues: DEFAULT_VALUES,
  });

  const {
    register,
    control,
    handleSubmit,
    reset,
    setError,
    setValue,
    formState: { errors, isDirty, isSubmitting },
  } = form;

  function closeAndReset() {
    onOpenChange(false);
    reset(DEFAULT_VALUES);
    setFormError(null);
  }

  function attemptClose() {
    if (mutation.isPending) return;
    if (isDirty) {
      setConfirmDiscardOpen(true);
      return;
    }
    closeAndReset();
  }

  async function onSubmit(input: ProvisionTenantInput) {
    setFormError(null);
    try {
      const created = await mutation.mutateAsync(input);
      toast.success(`Tenant ${created.name} provisioned`);
      closeAndReset();
      // Phase 5n.8a (2026-05-19): auto-navigate restored. Sanjeev's
      // Step 6.20.1 fix (f37a66c) provisions the tenant-root org_node
      // on POST /tenants, which makes GET /tenants/{id} return 200 for
      // newly-created tenants. The 5n.5 sidestep is no longer needed.
      router.replace(`/superadmin/tenants?tenant=${created.id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "VALIDATION_ERROR" && err.details && typeof err.details === "object") {
          const fieldErrors = (err.details as { field_errors?: Record<string, string[]> })
            .field_errors;
          if (fieldErrors) {
            for (const [field, messages] of Object.entries(fieldErrors)) {
              if (field in DEFAULT_VALUES) {
                setError(field as keyof ProvisionTenantInput, {
                  type: "server",
                  message: messages[0] ?? "Invalid value",
                });
              }
            }
          }
          setFormError(err.message);
          return;
        }
        if (err.code === "DISPLAY_CODE_TAKEN") {
          setError("display_code", {
            type: "server",
            message: "Display code is already in use",
          });
          return;
        }
        if (err.status >= 500) {
          toast.error("Could not provision tenant. Please try again.");
          return;
        }
        setFormError(err.message);
        return;
      }
      toast.error("Could not provision tenant. Please try again.");
    }
  }

  const tiers = lookups.data?.tenant_tiers ?? [];
  const industries = lookups.data?.tenant_industries ?? [];
  const regions = lookups.data?.tenant_regions ?? [];

  return (
    <>
      <Modal
        open={open}
        onOpenChange={(next) => {
          if (!next) attemptClose();
          else onOpenChange(true);
        }}
        size="lg"
        title="Provision new tenant"
        subtitle="Create a client organization with module access."
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={attemptClose}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              form="provision-tenant-form"
              disabled={isSubmitting}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  Provisioning...
                </>
              ) : (
                "Provision tenant"
              )}
            </Button>
          </div>
        }
      >
        <form
          id="provision-tenant-form"
          onSubmit={handleSubmit(onSubmit)}
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
                <p className="font-medium">Could not provision tenant.</p>
                <p className="text-muted-foreground">{formError}</p>
              </div>
            </div>
          ) : null}

          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="name" required>Tenant name</FieldLabel>
            <Input id="name" {...register("name")} placeholder="Acme Foods Inc." />
            <FieldError message={errors.name?.message} />
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="display_code">Display code</FieldLabel>
            <Input
              id="display_code"
              {...register("display_code", {
                onBlur: (e) => {
                  const v = e.target.value;
                  if (v && v !== v.toLowerCase()) {
                    setValue("display_code", v.toLowerCase(), { shouldValidate: true });
                  }
                },
              })}
              placeholder="acme-retail"
            />
            <p className="text-xs text-muted-foreground">
              Auto-generated from name if blank. Lowercase letters, numbers, hyphens; 3-64 chars.
            </p>
            <FieldError message={errors.display_code?.message} />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <FieldLabel htmlFor="industry" required>Industry</FieldLabel>
              <Controller
                name="industry"
                control={control}
                render={({ field }) => (
                  <select id="industry" {...field} className={SELECT_CLASS}>
                    {industries.map((i) => (
                      <option key={i.code} value={i.code}>
                        {i.display_name}
                      </option>
                    ))}
                  </select>
                )}
              />
              <FieldError message={errors.industry?.message} />
            </div>
            <div className="flex flex-col gap-1">
              <FieldLabel htmlFor="country" required>Country</FieldLabel>
              <Input id="country" {...register("country")} placeholder="USA" />
              <FieldError message={errors.country?.message} />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <FieldLabel htmlFor="tier" required>Tier</FieldLabel>
              <Controller
                name="tier"
                control={control}
                render={({ field }) => (
                  <select id="tier" {...field} className={SELECT_CLASS}>
                    {tiers.map((t) => (
                      <option key={t.code} value={t.code}>
                        {t.display_name}
                      </option>
                    ))}
                  </select>
                )}
              />
              <FieldError message={errors.tier?.message} />
            </div>
            <div className="flex flex-col gap-1">
              <FieldLabel htmlFor="region" required>Region</FieldLabel>
              <Controller
                name="region"
                control={control}
                render={({ field }) => (
                  <select id="region" {...field} className={SELECT_CLASS}>
                    {regions.map((r) => (
                      <option key={r.code} value={r.code}>
                        {r.display_name}
                      </option>
                    ))}
                  </select>
                )}
              />
              <FieldError message={errors.region?.message} />
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="primary_contact_name" required>Primary contact</FieldLabel>
            <Input
              id="primary_contact_name"
              {...register("primary_contact_name")}
              placeholder="Jane Smith"
            />
            <FieldError message={errors.primary_contact_name?.message} />
          </div>

          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="contact_email" required>Contact email</FieldLabel>
            <Input
              id="contact_email"
              type="email"
              {...register("contact_email")}
              placeholder="jane@acmefoods.com"
            />
            <FieldError message={errors.contact_email?.message} />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <FieldLabel htmlFor="number_of_stores" required>Stores</FieldLabel>
              <Input
                id="number_of_stores"
                type="number"
                inputMode="numeric"
                min={1}
                {...register("number_of_stores", { valueAsNumber: true })}
              />
              <FieldError message={errors.number_of_stores?.message} />
            </div>
            <div className="flex flex-col gap-1">
              <FieldLabel htmlFor="monthly_revenue_usd">Monthly revenue (USD)</FieldLabel>
              <div className="relative">
                <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
                  $
                </span>
                <Input
                  id="monthly_revenue_usd"
                  inputMode="decimal"
                  className="pl-6"
                  placeholder="500.00"
                  {...register("monthly_revenue_usd")}
                />
              </div>
              <FieldError message={errors.monthly_revenue_usd?.message} />
            </div>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={confirmDiscardOpen}
        onOpenChange={setConfirmDiscardOpen}
        title="Discard changes?"
        body="Closing the form will discard your tenant details. You can re-open and start over."
        confirmLabel="Discard"
        cancelLabel="Keep editing"
        variant="destructive"
        onConfirm={() => {
          setConfirmDiscardOpen(false);
          closeAndReset();
        }}
      />
    </>
  );
}
