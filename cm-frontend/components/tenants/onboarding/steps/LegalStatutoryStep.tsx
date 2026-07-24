"use client";

import { useEffect } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { ApiError } from "@/lib/api/client";
import { useOnboardingLookups } from "@/lib/hooks/use-onboarding-lookups";
import {
  useLegalProfile,
  usePutLegalProfile,
  usePutTaxRegistrations,
  useTaxRegistrations,
} from "@/lib/hooks/use-onboarding";
import { legalProfileSchema, taxRegistrationRowSchema } from "@/lib/schemas/onboarding/legal";
import {
  FieldError,
  FieldLabel,
  FormErrorAlert,
  SELECT_CLASS,
} from "@/components/tenants/onboarding/fields";
import { StepShell } from "@/components/tenants/onboarding/StepShell";
import { WizardFooter } from "@/components/tenants/onboarding/WizardFooter";
import type { StepProps } from "@/components/tenants/onboarding/step-props";

const FORM_ID = "onboarding-legal-form";

const stepSchema = z.object({
  legal: legalProfileSchema,
  items: z.array(taxRegistrationRowSchema).superRefine((items, ctx) => {
    const seen = new Set<string>();
    items.forEach((row, index) => {
      const key = `${row.registration_type} ${row.registration_number}`;
      if (seen.has(key)) {
        ctx.addIssue({
          code: "custom",
          message: "Duplicate: same type and number already added",
          path: [index, "registration_number"],
        });
      } else {
        seen.add(key);
      }
    });
  }),
});

type StepForm = z.infer<typeof stepSchema>;

const EMPTY: StepForm = {
  legal: {
    legal_entity_name: "",
    entity_type: "",
    registration_number: "",
    incorporation_date: "",
    registered_address: "",
  },
  items: [],
};

export function LegalStatutoryStep({ tenantId, onSaved, onBack, setDirty }: StepProps) {
  const lookups = useOnboardingLookups();
  const entityTypes = lookups.data?.entity_type ?? [];
  const regTypes = lookups.data?.tax_registration_type ?? [];

  const legalQuery = useLegalProfile(tenantId);
  const taxQuery = useTaxRegistrations(tenantId);
  const putLegal = usePutLegalProfile(tenantId);
  const putTax = usePutTaxRegistrations(tenantId);

  const form = useForm<StepForm>({
    resolver: zodResolver(stepSchema),
    mode: "onBlur",
    defaultValues: EMPTY,
  });
  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors, isDirty, isSubmitting },
  } = form;
  const { fields, append, remove } = useFieldArray({ control, name: "items" });

  const loaded = !legalQuery.isLoading && !taxQuery.isLoading;
  useEffect(() => {
    if (!loaded) return;
    reset({
      legal: legalQuery.data
        ? {
            legal_entity_name: legalQuery.data.legal_entity_name,
            entity_type: legalQuery.data.entity_type,
            registration_number: legalQuery.data.registration_number ?? "",
            incorporation_date: legalQuery.data.incorporation_date ?? "",
            registered_address: legalQuery.data.registered_address ?? "",
          }
        : EMPTY.legal,
      items: (taxQuery.data?.items ?? []).map((r) => ({
        registration_type: r.registration_type,
        registration_number: r.registration_number,
        jurisdiction: r.jurisdiction ?? "",
      })),
    });
    // Reset only when the loaded data identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, legalQuery.data, taxQuery.data]);

  useEffect(() => setDirty(isDirty), [isDirty, setDirty]);

  async function onSubmit(values: StepForm) {
    try {
      await putLegal.mutateAsync({
        legal_entity_name: values.legal.legal_entity_name.trim(),
        entity_type: values.legal.entity_type,
        registration_number: values.legal.registration_number?.trim() || null,
        incorporation_date: values.legal.incorporation_date?.trim() || null,
        registered_address: values.legal.registered_address?.trim() || null,
      });
      await putTax.mutateAsync({
        items: values.items.map((r) => ({
          registration_type: r.registration_type,
          registration_number: r.registration_number.trim(),
          jurisdiction: r.jurisdiction?.trim() || null,
        })),
      });
      setDirty(false);
      onSaved();
    } catch (err) {
      handleSectionError(err);
    }
  }

  function handleSectionError(err: unknown) {
    if (err instanceof ApiError) {
      if (err.code === "DUPLICATE_SECTION_ROW") {
        form.setError("root", { type: "server", message: err.message });
        return;
      }
      if (err.code === "INVALID_LOOKUP_CODE") {
        form.setError("root", { type: "server", message: err.message });
        return;
      }
      if (err.status >= 500) {
        toast.error("Could not save. Please try again.");
        return;
      }
      form.setError("root", { type: "server", message: err.message });
      return;
    }
    toast.error("Could not save. Please try again.");
  }

  if (!loaded) {
    return <StepShell title="Legal & statutory"><Skeleton variant="card" /></StepShell>;
  }
  if (legalQuery.error || taxQuery.error) {
    return (
      <StepShell title="Legal & statutory">
        <ErrorInline
          message="Could not load this section."
          onRetry={() => { void legalQuery.refetch(); void taxQuery.refetch(); }}
        />
      </StepShell>
    );
  }

  return (
    <StepShell
      title="Legal & statutory"
      description="The legal entity and its tax registrations."
      footer={<WizardFooter formId={FORM_ID} saving={isSubmitting} onBack={onBack} />}
    >
      <form id={FORM_ID} onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-6" noValidate>
        {errors.root ? <FormErrorAlert title="Could not save legal details." message={errors.root.message ?? ""} /> : null}

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="legal_entity_name" required>Legal entity name</FieldLabel>
            <Input id="legal_entity_name" {...register("legal.legal_entity_name")} placeholder="Acme Retail Private Limited" />
            <FieldError message={errors.legal?.legal_entity_name?.message} />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <FieldLabel htmlFor="entity_type" required>Entity type</FieldLabel>
              <select id="entity_type" className={SELECT_CLASS} {...register("legal.entity_type")}>
                <option value="">Select...</option>
                {entityTypes.map((e) => (
                  <option key={e.code} value={e.code}>{e.display_name}</option>
                ))}
              </select>
              <FieldError message={errors.legal?.entity_type?.message} />
            </div>
            <div className="flex flex-col gap-1">
              <FieldLabel htmlFor="registration_number">Registration number</FieldLabel>
              <Input id="registration_number" {...register("legal.registration_number")} placeholder="U12345MH2020PTC000000" />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <FieldLabel htmlFor="incorporation_date">Incorporation date</FieldLabel>
              <Input id="incorporation_date" type="date" {...register("legal.incorporation_date")} />
            </div>
            <div className="flex flex-col gap-1">
              <FieldLabel htmlFor="registered_address">Registered address</FieldLabel>
              <Input id="registered_address" {...register("legal.registered_address")} placeholder="1 Market Road" />
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium">Tax registrations</h3>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => append({ registration_type: "", registration_number: "", jurisdiction: "" })}
            >
              <Plus className="mr-1 h-3.5 w-3.5" /> Add registration
            </Button>
          </div>

          {fields.length === 0 ? (
            <p className="text-sm text-muted-foreground">No tax registrations. Add one if applicable.</p>
          ) : (
            <div className="flex flex-col gap-3">
              {fields.map((field, index) => (
                <div key={field.id} className="grid grid-cols-1 gap-2 rounded-md border border-border p-3 sm:grid-cols-[1fr_1fr_1fr_auto]">
                  <div className="flex flex-col gap-1">
                    <FieldLabel htmlFor={`tax-type-${index}`}>Type</FieldLabel>
                    <select id={`tax-type-${index}`} className={SELECT_CLASS} {...register(`items.${index}.registration_type` as const)}>
                      <option value="">Select...</option>
                      {regTypes.map((t) => (
                        <option key={t.code} value={t.code}>{t.display_name}</option>
                      ))}
                    </select>
                    <FieldError message={errors.items?.[index]?.registration_type?.message} />
                  </div>
                  <div className="flex flex-col gap-1">
                    <FieldLabel htmlFor={`tax-num-${index}`}>Number</FieldLabel>
                    <Input id={`tax-num-${index}`} {...register(`items.${index}.registration_number` as const)} />
                    <FieldError message={errors.items?.[index]?.registration_number?.message} />
                  </div>
                  <div className="flex flex-col gap-1">
                    <FieldLabel htmlFor={`tax-juris-${index}`}>Jurisdiction</FieldLabel>
                    <Input id={`tax-juris-${index}`} {...register(`items.${index}.jurisdiction` as const)} placeholder="MH" />
                  </div>
                  <div className="flex items-end">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Remove registration ${index + 1}`}
                      onClick={() => remove(index)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </form>
    </StepShell>
  );
}
