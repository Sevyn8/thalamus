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
          {/* THE ONE CONTENT CONTAINER, matching ver2's `.content`
              (dis-ui-ver2/src/index.css:356-360: max-width 1240px, padding
              24px 26px 90px). ver2 has exactly ONE — Shell.tsx:233 wraps every
              route in it and no page type narrows below it.

              THIS DID NOT EXIST BEFORE. The chrome-alignment phase ported ver2's
              colour and chrome but not its container, so cm-frontend had THREE
              widths: unbounded list pages, an 840px Synapse column, and various
              centred caps elsewhere. Capping here rather than per page is what
              makes it one system instead of a convention every new page has to
              remember.

              pb-[90px] is ver2's, and it is generous on purpose: content that
              ends flush against the viewport bottom reads as truncated. */}
          <main className="flex-1">
            <div className="mx-auto w-full max-w-[1240px] pb-[90px]">{children}</div>
          </main>
        </div>
      </div>
    </AuthBoundary>
  );
}
