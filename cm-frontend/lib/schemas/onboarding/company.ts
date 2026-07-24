import { z } from "zod";

import { DISPLAY_CODE_REGEX } from "@/lib/schemas/provision-tenant";

const MONEY_REGEX = /^\d+(\.\d{1,2})?$/;

// Wizard Step 1 (Company profile). Distinct from provisionTenantSchema:
// region / tier / industry are validated as non-empty strings (the selects
// are lookups-driven, and the backend enum is the real gate) rather than a
// hardcoded z.enum. That deliberately avoids the drift that left
// provisionTenantSchema.region at ["US","EU"] without INDIA; the wizard's
// region select shows every tenant_region lookup (INDIA included), and the
// value is cast to the generated TenantRegion union when the payload is
// built. ProvisionTenantModal and its schema are untouched (Slice 4 is
// additive).
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
