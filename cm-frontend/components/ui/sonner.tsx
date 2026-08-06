"use client";

import { useTheme } from "next-themes";
import { Toaster as Sonner, type ToasterProps } from "sonner";
import {
  CircleCheckIcon,
  InfoIcon,
  TriangleAlertIcon,
  OctagonXIcon,
  Loader2Icon,
} from "lucide-react";

const Toaster = ({ ...props }: ToasterProps) => {
  const { theme = "system" } = useTheme();

  return (
    <Sonner
      theme={theme as ToasterProps["theme"]}
      className="toaster group"
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      // ONE COLOUR AUTHORITY. Sonner ships `richColors`, which paints toasts from its own
      // built-in palette — a THIRD set of status colours alongside ver2's tokens and the Chip
      // triples, and the one nobody would think to update when the palette moves. It is not
      // enabled here and must not be: every variant below resolves through the same
      // --success/--warning/--danger triples the badges use, so a toast and a chip reporting
      // the same condition are the same colour by construction rather than by coincidence.
      //
      // Both modes come from the token layer — no per-variant dark override (Chips precedent).
      style={
        {
          "--normal-bg": "var(--surface)",
          "--normal-text": "var(--foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius-md)",

          "--success-bg": "var(--success-bg)",
          "--success-text": "var(--success)",
          "--success-border": "var(--success-line)",

          "--warning-bg": "var(--warning-bg)",
          "--warning-text": "var(--warning)",
          "--warning-border": "var(--warning-line)",

          "--error-bg": "var(--danger-bg)",
          "--error-text": "var(--danger)",
          "--error-border": "var(--danger-line)",

          "--info-bg": "var(--info-bg)",
          "--info-text": "var(--info)",
          "--info-border": "var(--info-line)",
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          // .cn-toast WAS REFERENCED HERE AND DEFINED NOWHERE — inert since this component
          // was added. It now carries the shadow, the one part of §9.4's card recipe Sonner
          // exposes no variable for.
          toast: "cn-toast",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
