import { z } from "zod";

export const DISPLAY_CODE_REGEX = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/;
const MONEY_REGEX = /^\d+(\.\d{1,2})?$/;

export const provisionTenantSchema = z.object({
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
  region: z.enum(["US", "EU"]),
  tier: z.enum(["ENTERPRISE", "MID_MARKET", "SMB", "SINGLE_STORE"]),
  industry: z.enum([
    "CONVENIENCE_FUEL",
    "CONVENIENCE",
    "GROCERY",
    "HYPERMART",
    "SPECIALITY_GROCERY",
    "ORGANIC_GROCERY",
  ]),
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

export type ProvisionTenantInput = z.infer<typeof provisionTenantSchema>;
