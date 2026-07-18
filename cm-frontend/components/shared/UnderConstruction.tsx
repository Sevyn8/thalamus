import { Construction } from "lucide-react";

import { EmptyState } from "./EmptyState";

// Placeholder content for routes scaffolded ahead of their feature
// chunks. DIS Phase 5b.1 creates 44 v1 placeholder pages so the sidebar
// nav navigates cleanly; each Phase 5c chunk replaces a subset of these
// with real page content. The `route` prop is the canonical path
// pattern (e.g. "/dis/sources/[id]") so the placeholder identifies
// which route the reader landed on without depending on Next.js params.

export type UnderConstructionProps = {
  route: string;
  title?: string;
};

export function UnderConstruction({ route, title }: UnderConstructionProps) {
  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <EmptyState
        icon={<Construction />}
        title={title ?? "Under construction"}
        body={`The ${route} page is scaffolded but its feature chunk hasn't shipped yet.`}
      />
    </div>
  );
}
