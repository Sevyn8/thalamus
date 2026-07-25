"use client";

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";

import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { ApiError } from "@/lib/api/client";
import { useOnboardingLookups } from "@/lib/hooks/use-onboarding-lookups";
import { useBillingProfile, usePutBillingProfile } from "@/lib/hooks/use-onboarding";
import {
  billingProfileSchema,
  type BillingProfileInput,
} from "@/lib/schemas/onboarding/billing";
import {
  FieldError,
  FieldLabel,
  FormErrorAlert,
  SELECT_CLASS,
} from "@/components/tenants/onboarding/fields";
import { StepShell } from "@/components/tenants/onboarding/StepShell";
import { WizardFooter } from "@/components/tenants/onboarding/WizardFooter";
import type { StepProps } from "@/components/tenants/onboarding/step-props";

const FORM_ID = "onboarding-billing-form";

const EMPTY: BillingProfileInput = {
  payment_terms: "",
  currency: "",
  billing_email: "",
  billing_contact_name: "",
  billing_address: "",
};

export function BillingFinanceStep({ tenantId, onSaved, onBack, setDirty, mode }: StepProps) {
  const lookups = useOnboardingLookups();
  const paymentTerms = lookups.data?.payment_terms ?? [];
  const currencies = lookups.data?.currency ?? [];

  const query = useBillingProfile(tenantId);
  const put = usePutBillingProfile(tenantId);

  const form = useForm<BillingProfileInput>({
    resolver: zodResolver(billingProfileSchema),
    mode: "onBlur",
    defaultValues: EMPTY,
  });
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isDirty, isSubmitting },
  } = form;

  useEffect(() => {
    if (query.isLoading) return;
    reset(
      query.data
        ? {
            payment_terms: query.data.payment_terms ?? "",
            currency: query.data.currency ?? "",
            billing_email: query.data.billing_email ?? "",
            billing_contact_name: query.data.billing_contact_name ?? "",
            billing_address: query.data.billing_address ?? "",
          }
        : EMPTY,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query.isLoading, query.data]);

  useEffect(() => setDirty(isDirty), [isDirty, setDirty]);

  async function onSubmit(values: BillingProfileInput) {
    try {
      await put.mutateAsync({
        payment_terms: values.payment_terms?.trim() || null,
        currency: values.currency?.trim() || null,
        billing_email: values.billing_email?.trim().toLowerCase() || null,
        billing_contact_name: values.billing_contact_name?.trim() || null,
        billing_address: values.billing_address?.trim() || null,
      });
      setDirty(false);
      onSaved();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "INVALID_LOOKUP_CODE") {
          setError("root", { type: "server", message: err.message });
          return;
        }
        if (err.status >= 500) {
          toast.error("Could not save. Please try again.");
          return;
        }
        setError("root", { type: "server", message: err.message });
        return;
      }
      toast.error("Could not save. Please try again.");
    }
  }

  if (query.isLoading) {
    return <StepShell title="Billing & finance"><Skeleton variant="card" /></StepShell>;
  }
  if (query.error) {
    return (
      <StepShell title="Billing & finance">
        <ErrorInline message="Could not load this section." onRetry={() => query.refetch()} />
      </StepShell>
    );
  }

  return (
    <StepShell
      title="Billing & finance"
      description="How this client is billed."
      footer={<WizardFooter formId={FORM_ID} saving={isSubmitting} onBack={onBack} continueLabel={mode === "edit" ? "Save changes" : undefined} />}
    >
      <form id={FORM_ID} onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
        {errors.root ? <FormErrorAlert title="Could not save billing details." message={errors.root.message ?? ""} /> : null}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="payment_terms">Payment terms</FieldLabel>
            <select id="payment_terms" className={SELECT_CLASS} {...register("payment_terms")}>
              <option value="">Select...</option>
              {paymentTerms.map((p) => (
                <option key={p.code} value={p.code}>{p.display_name}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <FieldLabel htmlFor="currency">Currency</FieldLabel>
            <select id="currency" className={SELECT_CLASS} {...register("currency")}>
              <option value="">Select...</option>
              {currencies.map((c) => (
                <option key={c.code} value={c.code}>{c.display_name}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="billing_email">Billing email</FieldLabel>
          <Input id="billing_email" type="email" {...register("billing_email")} placeholder="billing@acme.example.com" />
          <FieldError message={errors.billing_email?.message} />
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="billing_contact_name">Billing contact name</FieldLabel>
          <Input id="billing_contact_name" {...register("billing_contact_name")} placeholder="Finance Team" />
        </div>

        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="billing_address">Billing address</FieldLabel>
          <Input id="billing_address" {...register("billing_address")} placeholder="1 Market Road" />
        </div>
      </form>
    </StepShell>
  );
}
