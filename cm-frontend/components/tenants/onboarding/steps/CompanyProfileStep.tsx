"use client";

import { useEffect } from "react";
import { Controller, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";

import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { ApiError } from "@/lib/api/client";
import { tenantsApi, type TenantPatchPayload } from "@/lib/api/tenants";
import { useLookups } from "@/lib/hooks/use-lookups";
import { useTenant } from "@/lib/hooks/use-tenants";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  onboardingCompanySchema,
  type OnboardingCompanyInput,
} from "@/lib/schemas/onboarding/company";
import type {
  TenantCreateRequest,
  TenantDetail,
  TenantIndustry,
  TenantRegion,
  TenantTier,
} from "@/types/api";
import {
  FieldError,
  FieldLabel,
  FormErrorAlert,
  SELECT_CLASS,
} from "@/components/tenants/onboarding/fields";
import { WizardFooter } from "@/components/tenants/onboarding/WizardFooter";
import { StepShell } from "@/components/tenants/onboarding/StepShell";
import type { WizardMode } from "@/components/tenants/onboarding/step-props";

const FORM_ID = "onboarding-company-form";

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

// The backend's INVALID_TENANT_FIELD message embeds the offending column in
// single quotes ("Invalid value for 'monthly_revenue_as_of_date': ..."; the
// field is not in the envelope's details per the Q7 convention). Map it back
// to the matching form field so the error anchors to the right input -- and
// since revenue and its as-of date sit in the same row, a consistency error
// naming the date renders right next to the revenue it belongs to.
function fieldForInvalidTenantField(
  message: string,
): keyof OnboardingCompanyInput {
  const named = /'([^']+)'/.exec(message)?.[1];
  if (named === "monthly_revenue_as_of_date") return "monthly_revenue_as_of_date";
  if (named === "number_of_stores_as_of_date") return "number_of_stores_as_of_date";
  if (named === "number_of_stores") return "number_of_stores";
  return "monthly_revenue_usd";
}

const EMPTY: OnboardingCompanyInput = {
  name: "",
  display_code: "",
  region: "US",
  tier: "SMB",
  industry: "",
  country: "",
  primary_contact_name: "",
  contact_email: "",
  number_of_stores: 1,
  number_of_stores_as_of_date: "",
  monthly_revenue_usd: "",
  monthly_revenue_as_of_date: "",
};

function fromTenant(t: TenantDetail): OnboardingCompanyInput {
  return {
    name: t.name,
    display_code: t.display_code ?? "",
    region: t.region,
    tier: t.tier ?? "",
    industry: t.industry ?? "",
    country: t.country ?? "",
    primary_contact_name: t.primary_contact_name ?? "",
    contact_email: t.contact_email ?? "",
    number_of_stores: t.number_of_stores ?? 1,
    number_of_stores_as_of_date: t.number_of_stores_as_of_date ?? "",
    monthly_revenue_usd: t.monthly_revenue_usd ?? "",
    monthly_revenue_as_of_date: t.monthly_revenue_as_of_date ?? "",
  };
}

export type CompanyProfileStepProps = {
  tenantId: string | null;
  onCreated: (id: string) => void;
  onSaved: () => void;
  onBack: (() => void) | null;
  setDirty: (dirty: boolean) => void;
  // "edit" when this step is the standalone edit surface
  // (non-ONBOARDING tenant); "onboarding" for create/resume. Create is
  // always onboarding regardless.
  mode: WizardMode;
};

export function CompanyProfileStep(props: CompanyProfileStepProps) {
  const { tenantId } = props;
  if (tenantId === null) {
    return <CompanyCreate {...props} />;
  }
  return <CompanyEdit {...props} tenantId={tenantId} />;
}

// ---- shared field rows -----------------------------------------------------

function CompanyFields({
  form,
  regionDisabled,
}: {
  form: ReturnType<typeof useForm<OnboardingCompanyInput>>;
  regionDisabled: boolean;
}) {
  const lookups = useLookups();
  const tiers = lookups.data?.tenant_tiers ?? [];
  const industries = lookups.data?.tenant_industries ?? [];
  const regions = lookups.data?.tenant_regions ?? [];
  const {
    register,
    control,
    formState: { errors },
  } = form;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <FieldLabel htmlFor="name" required>Tenant name</FieldLabel>
        <Input id="name" {...register("name")} placeholder="Acme Foods Inc." />
        <FieldError message={errors.name?.message} />
      </div>

      <div className="flex flex-col gap-1">
        <FieldLabel htmlFor="display_code">Display code</FieldLabel>
        <Input id="display_code" {...register("display_code")} placeholder="acme-retail" />
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
                <option value="">Select...</option>
                {industries.map((i) => (
                  <option key={i.code} value={i.code}>{i.display_name}</option>
                ))}
              </select>
            )}
          />
          <FieldError message={errors.industry?.message} />
        </div>
        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="country" required>Country</FieldLabel>
          <Input id="country" {...register("country")} placeholder="India" />
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
                <option value="">Select...</option>
                {tiers.map((t) => (
                  <option key={t.code} value={t.code}>{t.display_name}</option>
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
              <select
                id="region"
                {...field}
                disabled={regionDisabled}
                className={SELECT_CLASS}
              >
                {regions.map((r) => (
                  <option key={r.code} value={r.code}>{r.display_name}</option>
                ))}
              </select>
            )}
          />
          {regionDisabled ? (
            <p className="text-xs text-muted-foreground">
              Region is fixed after the tenant is created.
            </p>
          ) : null}
          <FieldError message={errors.region?.message} />
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <FieldLabel htmlFor="primary_contact_name" required>Primary contact</FieldLabel>
        <Input id="primary_contact_name" {...register("primary_contact_name")} placeholder="Jane Smith" />
        <FieldError message={errors.primary_contact_name?.message} />
      </div>

      <div className="flex flex-col gap-1">
        <FieldLabel htmlFor="contact_email" required>Contact email</FieldLabel>
        <Input id="contact_email" type="email" {...register("contact_email")} placeholder="jane@acmefoods.com" />
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
          <FieldLabel htmlFor="number_of_stores_as_of_date" required>Stores as-of date</FieldLabel>
          <Input
            id="number_of_stores_as_of_date"
            type="date"
            {...register("number_of_stores_as_of_date")}
          />
          <FieldError message={errors.number_of_stores_as_of_date?.message} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="monthly_revenue_usd">Monthly revenue (USD)</FieldLabel>
          <Input
            id="monthly_revenue_usd"
            inputMode="decimal"
            placeholder="500.00"
            {...register("monthly_revenue_usd")}
          />
          <FieldError message={errors.monthly_revenue_usd?.message} />
        </div>
        <div className="flex flex-col gap-1">
          <FieldLabel htmlFor="monthly_revenue_as_of_date">Revenue as-of date</FieldLabel>
          <Input
            id="monthly_revenue_as_of_date"
            type="date"
            {...register("monthly_revenue_as_of_date")}
          />
          <p className="text-xs text-muted-foreground">
            Required when a monthly revenue figure is set.
          </p>
          <FieldError message={errors.monthly_revenue_as_of_date?.message} />
        </div>
      </div>
    </div>
  );
}

// ---- create mode -----------------------------------------------------------

function CompanyCreate({ onCreated, setDirty }: CompanyProfileStepProps) {
  const qc = useQueryClient();
  const form = useForm<OnboardingCompanyInput>({
    resolver: zodResolver(onboardingCompanySchema),
    mode: "onBlur",
    defaultValues: EMPTY,
  });
  const {
    handleSubmit,
    setError,
    formState: { errors, isDirty, isSubmitting },
  } = form;

  useEffect(() => {
    setDirty(isDirty);
  }, [isDirty, setDirty]);

  useEffect(() => {
    // Default the stores as-of date to today for a new tenant. Done here
    // (client-only, shouldDirty:false) rather than in defaultValues so the
    // static-prerendered create route does not bake the build date in, and
    // so an untouched form stays pristine for the discard guard.
    if (!form.getValues("number_of_stores_as_of_date")) {
      form.setValue("number_of_stores_as_of_date", todayIso(), {
        shouldDirty: false,
      });
    }
  }, [form]);

  const mutation = useMutation({
    mutationFn: (body: TenantCreateRequest) => tenantsApi.create(body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenants"] });
      void qc.invalidateQueries({ queryKey: ["tenant-stats"] });
    },
  });

  async function onSubmit(input: OnboardingCompanyInput) {
    const revenue = input.monthly_revenue_usd?.trim();
    const revenueDate = input.monthly_revenue_as_of_date?.trim();
    const display = input.display_code?.trim();
    const body: TenantCreateRequest = {
      name: input.name.trim(),
      region: input.region as TenantRegion,
      tier: input.tier as TenantTier,
      industry: input.industry as TenantIndustry,
      country: input.country.trim(),
      primary_contact_name: input.primary_contact_name.trim(),
      contact_email: input.contact_email.trim().toLowerCase(),
      number_of_stores: input.number_of_stores,
      number_of_stores_as_of_date: input.number_of_stores_as_of_date.trim() || todayIso(),
      display_code: display ? display.toLowerCase() : null,
      // Revenue and its as-of date go together or not at all (the schema's
      // cross-field rule guarantees this before we get here).
      monthly_revenue_usd: revenue ? revenue : null,
      monthly_revenue_as_of_date: revenue ? revenueDate || null : null,
    };
    try {
      const created = await mutation.mutateAsync(body);
      setDirty(false);
      toast.success(`Tenant ${created.name} created`);
      onCreated(created.id);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "DUPLICATE_TENANT_NAME") {
          setError("name", { type: "server", message: "A tenant with this name already exists" });
          return;
        }
        if (err.code === "DISPLAY_CODE_TAKEN") {
          setError("display_code", { type: "server", message: "Display code is already in use" });
          return;
        }
        if (err.code === "INVALID_TENANT_FIELD") {
          setError(fieldForInvalidTenantField(err.message), {
            type: "server",
            message: err.message,
          });
          return;
        }
        if (err.status >= 500) {
          toast.error("Could not create tenant. Please try again.");
          return;
        }
        toast.error(err.message);
        return;
      }
      toast.error("Could not create tenant. Please try again.");
    }
  }

  return (
    <StepShell
      title="Company profile"
      description="Create the client organization. It starts in Onboarding until you complete the wizard."
      footer={<WizardFooter formId={FORM_ID} saving={isSubmitting} onBack={null} continueLabel="Create & continue" />}
    >
      <form id={FORM_ID} onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
        {errors.root ? <FormErrorAlert title="Could not create tenant." message={errors.root.message ?? ""} /> : null}
        <CompanyFields form={form} regionDisabled={false} />
      </form>
    </StepShell>
  );
}

// ---- edit mode -------------------------------------------------------------

function CompanyEdit({
  tenantId,
  onSaved,
  onBack,
  setDirty,
  mode,
}: CompanyProfileStepProps & { tenantId: string }) {
  const qc = useQueryClient();
  const tenantQuery = useTenant(tenantId);
  const form = useForm<OnboardingCompanyInput>({
    resolver: zodResolver(onboardingCompanySchema),
    mode: "onBlur",
    defaultValues: EMPTY,
  });
  const {
    handleSubmit,
    reset,
    setError,
    formState: { isDirty, isSubmitting, dirtyFields },
  } = form;

  useEffect(() => {
    if (tenantQuery.data) reset(fromTenant(tenantQuery.data));
  }, [tenantQuery.data, reset]);

  useEffect(() => {
    setDirty(isDirty);
  }, [isDirty, setDirty]);

  const mutation = useMutation({
    mutationFn: (patch: TenantPatchPayload) => tenantsApi.patch(tenantId, patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenants"] });
      // ["tenant"] prefix, not ["tenant", tenantId] (which
      // does not prefix-match the per-user detail key ["tenant", userId,
      // id]), so the drawer reflects the edit on return.
      void qc.invalidateQueries({ queryKey: ["tenant"] });
    },
  });

  async function onSubmit(input: OnboardingCompanyInput) {
    // Diff PATCH: only changed fields (region is not patchable). If nothing
    // changed, skip the write and advance (avoids backend EMPTY_PATCH 422).
    const patch: TenantPatchPayload = {};
    const df = dirtyFields;
    if (df.name) patch.name = input.name.trim();
    if (df.display_code) patch.display_code = input.display_code?.trim() || null;
    if (df.country) patch.country = input.country.trim() || null;
    if (df.tier) patch.tier = (input.tier || null) as TenantTier | null;
    if (df.industry) patch.industry = (input.industry || null) as TenantIndustry | null;
    if (df.primary_contact_name) patch.primary_contact_name = input.primary_contact_name.trim() || null;
    if (df.contact_email) patch.contact_email = input.contact_email.trim().toLowerCase() || null;
    // Each value and its as-of date diff independently now that the dates
    // are real fields: a user can fix a dateless tenant by supplying just
    // the missing date. The schema's cross-field rule keeps the revenue
    // pair consistent before submit.
    if (df.number_of_stores) patch.number_of_stores = input.number_of_stores;
    if (df.number_of_stores_as_of_date) {
      patch.number_of_stores_as_of_date =
        input.number_of_stores_as_of_date.trim() || null;
    }
    if (df.monthly_revenue_usd) {
      patch.monthly_revenue_usd = input.monthly_revenue_usd?.trim() || null;
    }
    if (df.monthly_revenue_as_of_date) {
      patch.monthly_revenue_as_of_date =
        input.monthly_revenue_as_of_date?.trim() || null;
    }

    try {
      if (Object.keys(patch).length > 0) {
        await mutation.mutateAsync(patch);
      }
      setDirty(false);
      onSaved();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "DUPLICATE_TENANT_NAME") {
          setError("name", { type: "server", message: "A tenant with this name already exists" });
          return;
        }
        // The backend maps NUMERIC(15,2) overflow and the
        // revenue/stores CHECK constraints to 422 INVALID_TENANT_FIELD. The
        // as-of date fields are now real inputs, so the error anchors to the
        // exact field the backend named (which, for the revenue consistency
        // constraint, is the as-of date sitting right beside the revenue).
        if (err.code === "INVALID_TENANT_FIELD") {
          setError(fieldForInvalidTenantField(err.message), {
            type: "server",
            message: err.message,
          });
          return;
        }
        if (err.status >= 500) {
          toast.error("Could not save. Please try again.");
          return;
        }
        toast.error(err.message);
        return;
      }
      toast.error("Could not save. Please try again.");
    }
  }

  if (tenantQuery.isLoading) {
    return <StepShell title="Company profile" description=""><Skeleton variant="card" /></StepShell>;
  }
  if (tenantQuery.error || !tenantQuery.data) {
    return (
      <StepShell title="Company profile" description="">
        <ErrorInline message="Could not load this tenant." onRetry={() => tenantQuery.refetch()} />
      </StepShell>
    );
  }

  return (
    <StepShell
      title="Company profile"
      description="Edit the client organization's core details."
      footer={<WizardFooter formId={FORM_ID} saving={isSubmitting} onBack={onBack} continueLabel={mode === "edit" ? "Save changes" : undefined} />}
    >
      <form id={FORM_ID} onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
        <CompanyFields form={form} regionDisabled />
      </form>
    </StepShell>
  );
}
