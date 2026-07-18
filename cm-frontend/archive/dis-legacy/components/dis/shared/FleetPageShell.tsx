import type { ReactNode } from "react";

import { PageHeader } from "@/components/shared/PageHeader";

// Phase 5c.4d-prep: layout chrome for DIS fleet pages. Owns nothing
// behavioral — just PageHeader + the section padding/gap. Consumers
// render filters + table (and any page-specific elements like a
// "Load more" button on /dis/runs) as JSX children.
//
// Deliberately minimal. Slot enforcement (named slots like
// FleetPageShell.Filters) was considered and dropped — adds API
// surface for no current benefit and would complicate page-specific
// quirks. If a future surface needs structural enforcement (e.g.,
// a top-level toolbar above filters), revisit then.

type Props = {
  title: string;
  subtitle?: string;
  // Phase 5e.6: passthrough to PageHeader.rightSlot for "create" CTAs
  // and similar header-aligned controls (e.g., /dis/templates'
  // "+ Create Super Template").
  rightSlot?: ReactNode;
  children: ReactNode;
};

export function FleetPageShell({ title, subtitle, rightSlot, children }: Props) {
  return (
    <div className="flex flex-1 flex-col">
      <PageHeader title={title} subtitle={subtitle} rightSlot={rightSlot} />
      <section className="flex flex-col gap-6 px-6 py-6">{children}</section>
    </div>
  );
}
