import { z } from "zod";

// Wizard Step 3 (Billing & finance). All fields optional (mirrors
// BillingProfileUpsertRequest). billing_email, when present, must be a
// valid email; it is lowercased before the PUT (backend requires
// lower(email) per its DDL CHECK).
export const billingProfileSchema = z.object({
  payment_terms: z.string().trim().optional(),
  currency: z.string().trim().optional(),
  billing_email: z
    .union([z.literal(""), z.email("Invalid email address")])
    .optional(),
  billing_contact_name: z.string().trim().optional(),
  billing_address: z.string().trim().optional(),
});

export type BillingProfileInput = z.infer<typeof billingProfileSchema>;
