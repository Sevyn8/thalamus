import type { ReactNode } from "react";

// Per-step layout: sticky title/description header, scrollable body, and an
// optional footer (the Back / Save-&-continue bar). Keeps every step's
// chrome identical.
export function StepShell({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-border px-6 py-4">
        <h2 className="text-lg font-semibold">{title}</h2>
        {description ? (
          <p className="text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">{children}</div>
      {footer}
    </div>
  );
}
