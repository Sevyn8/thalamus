import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

// Shared field primitives for the onboarding wizard steps, matching the
// token classes used by EditTenantModal (and the retired ProvisionTenantModal) so the
// wizard forms are visually identical to the rest of the admin surface.

export const FIELD_INPUT_CLASS = cn(
  "h-9 w-full rounded-md border border-input bg-background px-2.5 py-1 text-sm",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
  "dark:bg-input/30",
);

export const SELECT_CLASS = cn(FIELD_INPUT_CLASS, "appearance-none");

export function FieldLabel({
  htmlFor,
  children,
  required,
}: {
  htmlFor: string;
  children: ReactNode;
  required?: boolean;
}) {
  return (
    <label htmlFor={htmlFor} className="text-xs font-medium text-foreground">
      {children}
      {required ? (
        <span className="ml-0.5 text-red-600 dark:text-red-400">*</span>
      ) : null}
    </label>
  );
}

export function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return (
    <p className="mt-1 text-xs text-red-600 dark:text-red-400">{message}</p>
  );
}

export function FormErrorAlert({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm dark:border-red-500/30 dark:bg-red-500/5"
    >
      <div>
        <p className="font-medium">{title}</p>
        <p className="text-muted-foreground">{message}</p>
      </div>
    </div>
  );
}
