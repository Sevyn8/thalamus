import type { ReactNode } from "react";

import { AuthBoundary } from "@/components/shared/AuthBoundary";
import { IthinaSidebar } from "@/components/chrome/IthinaSidebar";
import { TopBar } from "@/components/chrome/TopBar";
import { ImpersonationBanner } from "@/components/chrome/ImpersonationBanner";

export default function SuperadminLayout({ children }: { children: ReactNode }) {
  return (
    <AuthBoundary>
      <ImpersonationBanner />
      <div className="flex min-h-screen">
        <IthinaSidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />
          <main className="flex-1">{children}</main>
        </div>
      </div>
    </AuthBoundary>
  );
}
