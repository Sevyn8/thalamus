import { z } from "zod";

// Moved here in Slice 6 from the retired lib/schemas/provision-tenant.ts
// (the onboarding wizard is the only remaining consumer): a display code is
// lowercase alphanumerics + hyphens, 3-64 chars, no leading/trailing hyphen.
export const DISPLAY_CODE_REGEX = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/;

const MONEY_REGEX = /^\d+(\.\d{1,2})?$/;

// Wizard Step 1 (Company profile). region / tier / industry are validated
// as non-empty strings (the selects are lookups-driven, and the backend
// enum is the real gate) rather than a hardcoded z.enum: the region select
// shows every tenant_region lookup (INDIA included), and the value is cast
// to the generated TenantRegion union when the payload is built. This was
// deliberately independent of the retired provision-tenant schema, whose
// region enum omitted INDIA (Slice 6 removed it along with
// ProvisionTenantModal).
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
  monthly_revenue_usd: z
    .string()
    .trim()
    .optional()
    .refine(
      (v) => !v || MONEY_REGEX.test(v),
      "Decimal number with up to 2 places, e.g. 500.00",
    ),
});

export type OnboardingCompanyInput = z.infer<typeof onboardingCompanySchema>;
