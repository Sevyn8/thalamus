"use client";

import { useEffect } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { EmptyState } from "@/components/shared/EmptyState";
import { ApiError } from "@/lib/api/client";
import { useOnboardingLookups } from "@/lib/hooks/use-onboarding-lookups";
import { useContacts, usePutContacts } from "@/lib/hooks/use-onboarding";
import { contactsSchema, type ContactsInput } from "@/lib/schemas/onboarding/contacts";
import {
  FieldError,
  FieldLabel,
  FormErrorAlert,
  SELECT_CLASS,
} from "@/components/tenants/onboarding/fields";
import { StepShell } from "@/components/tenants/onboarding/StepShell";
import { WizardFooter } from "@/components/tenants/onboarding/WizardFooter";
import type { StepProps } from "@/components/tenants/onboarding/step-props";

const FORM_ID = "onboarding-contacts-form";

export function ContactsStep({ tenantId, onSaved, onBack, setDirty }: StepProps) {
  const lookups = useOnboardingLookups();
  const contactTypes = lookups.data?.contact_type ?? [];

  const query = useContacts(tenantId);
  const put = usePutContacts(tenantId);

  const form = useForm<ContactsInput>({
    resolver: zodResolver(contactsSchema),
    mode: "onBlur",
    defaultValues: { items: [] },
  });
  const {
    register,
    handleSubmit,
    reset,
    setError,
    control,
    formState: { errors, isDirty, isSubmitting },
  } = form;
  const { fields, append, remove } = useFieldArray({ control, name: "items" });

  useEffect(() => {
    if (query.isLoading) return;
    reset({
      items: (query.data?.items ?? []).map((c) => ({
        contact_type: c.contact_type,
        name: c.name,
        email: c.email ?? "",
        phone: c.phone ?? "",
      })),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query.isLoading, query.data]);

  useEffect(() => setDirty(isDirty), [isDirty, setDirty]);

  async function onSubmit(values: ContactsInput) {
    try {
      await put.mutateAsync({
        items: values.items.map((c) => ({
          contact_type: c.contact_type,
          name: c.name.trim(),
          email: c.email?.trim().toLowerCase() || null,
          phone: c.phone?.trim() || null,
        })),
      });
      setDirty(false);
      onSaved();
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "DUPLICATE_SECTION_ROW" || err.code === "INVALID_LOOKUP_CODE") {
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
    return <StepShell title="Contacts"><Skeleton variant="card" /></StepShell>;
  }
  if (query.error) {
    return (
      <StepShell title="Contacts">
        <ErrorInline message="Could not load this section." onRetry={() => query.refetch()} />
      </StepShell>
    );
  }

  return (
    <StepShell
      title="Contacts"
      description="Key people for this client. Add primary, billing, technical, or legal contacts."
      footer={<WizardFooter formId={FORM_ID} saving={isSubmitting} onBack={onBack} />}
    >
      <form id={FORM_ID} onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
        {errors.root ? <FormErrorAlert title="Could not save contacts." message={errors.root.message ?? ""} /> : null}

        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">Contacts</h3>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => append({ contact_type: "", name: "", email: "", phone: "" })}
          >
            <Plus className="mr-1 h-3.5 w-3.5" /> Add contact
          </Button>
        </div>

        {fields.length === 0 ? (
          <EmptyState
            title="No contacts yet"
            body="Add at least one contact for this client."
            action={{ label: "Add contact", onClick: () => append({ contact_type: "", name: "", email: "", phone: "" }) }}
          />
        ) : (
          <div className="flex flex-col gap-3">
            {fields.map((field, index) => (
              <div key={field.id} className="grid grid-cols-1 gap-2 rounded-md border border-border p-3 sm:grid-cols-[1fr_1fr_1fr_1fr_auto]">
                <div className="flex flex-col gap-1">
                  <FieldLabel htmlFor={`contact-type-${index}`}>Type</FieldLabel>
                  <select id={`contact-type-${index}`} className={SELECT_CLASS} {...register(`items.${index}.contact_type` as const)}>
                    <option value="">Select...</option>
                    {contactTypes.map((t) => (
                      <option key={t.code} value={t.code}>{t.display_name}</option>
                    ))}
                  </select>
                  <FieldError message={errors.items?.[index]?.contact_type?.message} />
                </div>
                <div className="flex flex-col gap-1">
                  <FieldLabel htmlFor={`contact-name-${index}`}>Name</FieldLabel>
                  <Input id={`contact-name-${index}`} {...register(`items.${index}.name` as const)} />
                  <FieldError message={errors.items?.[index]?.name?.message} />
                </div>
                <div className="flex flex-col gap-1">
                  <FieldLabel htmlFor={`contact-email-${index}`}>Email</FieldLabel>
                  <Input id={`contact-email-${index}`} type="email" {...register(`items.${index}.email` as const)} />
                  <FieldError message={errors.items?.[index]?.email?.message} />
                </div>
                <div className="flex flex-col gap-1">
                  <FieldLabel htmlFor={`contact-phone-${index}`}>Phone</FieldLabel>
                  <Input id={`contact-phone-${index}`} {...register(`items.${index}.phone` as const)} />
                </div>
                <div className="flex items-end">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Remove contact ${index + 1}`}
                    onClick={() => remove(index)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </form>
    </StepShell>
  );
}
