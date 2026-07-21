import type { ReactNode } from "react";

import { AuthBoundary } from "@/components/shared/AuthBoundary";
import { ImpersonationBanner } from "@/components/chrome/ImpersonationBanner";
import { UserMenu } from "@/components/chrome/UserMenu";

// Phase 5d.1: My Ithina launcher chrome. Bare-centered layout (no
// product sidebar, no ProductSwitcher) — this surface IS the
// product picker. A minimal top-right corner carries UserMenu so
// persona switching + theme work without forcing the full TopBar.
//
// AuthBoundary still gates: unauthenticated visits redirect to
// /auth/login. ImpersonationBanner is included so demo audiences see
// the same banner consistency as the rest of the app.
export default function MyIthinaLayout({ children }: { children: ReactNode }) {
  return (
    <AuthBoundary>
      <ImpersonationBanner />
      <div className="flex min-h-screen flex-col">
        <header className="flex h-14 items-center justify-end gap-2 border-b border-border bg-background/95 px-6 backdrop-blur supports-[backdrop-filter]:bg-background/80">
          <UserMenu />
        </header>
        <main className="flex-1">{children}</main>
      </div>
    </AuthBoundary>
  );
}
