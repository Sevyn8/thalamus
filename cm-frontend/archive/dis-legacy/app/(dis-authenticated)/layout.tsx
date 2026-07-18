import type { ReactNode } from "react";

import { AuthBoundary } from "@/components/shared/AuthBoundary";
import { DisSidebar } from "@/components/chrome/DisSidebar";
import { TopBar } from "@/components/chrome/TopBar";
import { ImpersonationBanner } from "@/components/chrome/ImpersonationBanner";

// Parallel route group to (authenticated). DIS routes live here so the
// DIS sidebar replaces — rather than nests beneath — the Ithina
// sidebar; nesting (authenticated)/dis/layout.tsx under the existing
// (authenticated)/layout.tsx would render both sidebars at once. URL
// paths unaffected (route groups are URL-invisible). Phase 5b.1.
export default function DisLayout({ children }: { children: ReactNode }) {
  return (
    <AuthBoundary>
      <ImpersonationBanner />
      <div className="flex min-h-screen">
        <DisSidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />
          <main className="flex-1">{children}</main>
        </div>
      </div>
    </AuthBoundary>
  );
}
