"use client";

import { Suspense, useEffect } from "react";
import { useRouter } from "next/navigation";

import { OnboardingWizard } from "@/components/tenants/onboarding/OnboardingWizard";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { hasPermission } from "@/lib/auth/permissions-check";

function OnboardNewInner() {
  const router = useRouter();
  const snapshot = useAuthSnapshot();

  // Same gate as "+ Provision tenant": ADMIN.TENANTS.CONFIGURE.GLOBAL.
  // Fail-closed during boot (permissions null while /me/permissions is in
  // flight); only a resolved-false redirects, mirroring the tenants page.
  const canConfigure = hasPermission(snapshot, "ADMIN", "TENANTS", "CONFIGURE", "GLOBAL");
  const grantsLoaded = snapshot?.permissions != null;

  useEffect(() => {
    if (grantsLoaded && !canConfigure) {
      router.replace("/superadmin/dashboard");
    }
  }, [grantsLoaded, canConfigure, router]);

  if (grantsLoaded && !canConfigure) return null;

  return <OnboardingWizard tenantId={null} />;
}

export default function OnboardNewPage() {
  return (
    <Suspense fallback={null}>
      <OnboardNewInner />
    </Suspense>
  );
}
