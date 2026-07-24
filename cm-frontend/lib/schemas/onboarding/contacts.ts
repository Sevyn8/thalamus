import { z } from "zod";

// Wizard Step 4 (Contacts, 1:N full-replace). The superRefine mirrors the
// backend DUPLICATE_SECTION_ROW guard (exact-duplicate contact rows) so the
// duplicate is surfaced inline before the PUT; the backend stays the
// authority if it still fires. email is optional but validated when present
// and lowercased before the PUT.
export const contactRowSchema = z.object({
  contact_type: z.string().min(1, "Type is required"),
  name: z.string().trim().min(1, "Name is required").max(200, "Max 200 characters"),
  email: z
    .union([z.literal(""), z.email("Invalid email address")])
    .optional(),
  phone: z.string().trim().optional(),
});

export const contactsSchema = z.object({
  items: z.array(contactRowSchema).superRefine((items, ctx) => {
    const seen = new Set<string>();
    items.forEach((row, index) => {
      const key = JSON.stringify([
        row.contact_type,
        row.name.trim(),
        (row.email ?? "").trim().toLowerCase(),
        (row.phone ?? "").trim(),
      ]);
      if (seen.has(key)) {
        ctx.addIssue({
          code: "custom",
          message: "Duplicate contact: identical row already added",
          path: [index, "name"],
        });
      } else {
        seen.add(key);
      }
    });
  }),
});

export type ContactsInput = z.infer<typeof contactsSchema>;
