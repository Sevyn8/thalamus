import { z } from "zod";

// The onboarding wizard is the only consumer: a display code is lowercase
// alphanumerics + hyphens, 3-64 chars, no leading/trailing hyphen.
export const DISPLAY_CODE_REGEX = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/;

const MONEY_REGEX = /^\d+(\.\d{1,2})?$/;

// Backend column is NUMERIC(15,2): 13 integer digits + 2 decimals, so the
// largest storable value is 9999999999999.99. Mirroring the bound here gives
// fast inline feedback (staging hit exactly this: a 909090909... value that
// tripped the backend 422). The backend remains the authority; this only
// short-circuits the obviously-too-large case before the round-trip.
const MAX_MONTHLY_REVENUE_USD = 9999999999999.99;

// Wizard Step 1 (Company profile). region / tier / industry are validated
// as non-empty strings (the selects are lookups-driven, and the backend
// enum is the real gate) rather than a hardcoded z.enum: the region select
// shows every tenant_region lookup (INDIA included), and the value is cast
// to the generated TenantRegion union when the payload is built. This was
// deliberately independent of the retired provision-tenant schema, whose
// region enum omitted INDIA.
export const onboardingCompanySchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Tenant name is required")
    .max(200, "Max 200 characters"),
  display_code: z
    .string()
    .trim()
    .optional()
    .refine(
      (v) => !v || DISPLAY_CODE_REGEX.test(v),
      "Lowercase letters, numbers, and hyphens; 3-64 chars; no leading/trailing hyphen",
    ),
  region: z.string().min(1, "Region is required"),
  tier: z.string().min(1, "Tier is required"),
  industry: z.string().min(1, "Industry is required"),
  country: z
    .string()
    .trim()
    .min(2, "Min 2 characters")
    .max(100, "Max 100 characters"),
  primary_contact_name: z
    .string()
    .trim()
    .min(1, "Primary contact is required")
    .max(200, "Max 200 characters"),
  contact_email: z.email("Invalid email address"),
  number_of_stores: z
    .number({ error: "Stores must be an integer" })
    .int("Stores must be an integer")
    .min(1, "Min 1 store"),
  // Store count is always set (min 1), so the backend's both-or-neither
  // consistency CHECK (ck_tenants_number_of_stores_as_of_consistency)
  // requires the as-of date too. It is exposed as a real field (the retired
  // EditTenantModal was the only surface that wrote it); create defaults it
  // to today.
  number_of_stores_as_of_date: z
    .string()
    .trim()
    .min(1, "As-of date is required"),
  monthly_revenue_usd: z
    .string()
    .trim()
    .optional()
    .refine(
      (v) => !v || MONEY_REGEX.test(v),
      "Decimal number with up to 2 places, e.g. 500.00",
    )
    .refine(
      (v) => !v || !MONEY_REGEX.test(v) || Number(v) <= MAX_MONTHLY_REVENUE_USD,
      "Value is too large (max 9,999,999,999,999.99)",
    ),
  // Revenue and its as-of date are both-or-neither (the backend
  // ck_tenants_monthly_revenue_as_of_consistency CHECK). Exposed so a user
  // can resolve the pair inline; the cross-field rule below anchors the
  // consistency error to whichever half is missing.
  monthly_revenue_as_of_date: z.string().trim().optional(),
}).superRefine((val, ctx) => {
  const revenue = val.monthly_revenue_usd?.trim();
  const revenueDate = val.monthly_revenue_as_of_date?.trim();
  if (revenue && !revenueDate) {
    ctx.addIssue({
      code: "custom",
      path: ["monthly_revenue_as_of_date"],
      message: "Add the as-of date for this revenue figure",
    });
  }
  if (!revenue && revenueDate) {
    ctx.addIssue({
      code: "custom",
      path: ["monthly_revenue_usd"],
      message: "Add the revenue figure for this as-of date",
    });
  }
});

export type OnboardingCompanyInput = z.infer<typeof onboardingCompanySchema>;
