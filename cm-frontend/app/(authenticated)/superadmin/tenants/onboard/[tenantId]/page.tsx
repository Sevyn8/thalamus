"use client";

import { Suspense, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

import { OnboardingWizard } from "@/components/tenants/onboarding/OnboardingWizard";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { hasPermission } from "@/lib/auth/permissions-check";

function OnboardResumeInner() {
  const router = useRouter();
  const params = useParams<{ tenantId: string }>();
  const tenantId = params.tenantId;
  const snapshot = useAuthSnapshot();

  const canConfigure = hasPermission(snapshot, "ADMIN", "TENANTS", "CONFIGURE", "GLOBAL");
  const grantsLoaded = snapshot?.permissions != null;

  useEffect(() => {
    if (grantsLoaded && !canConfigure) {
      router.replace("/superadmin/dashboard");
    }
  }, [grantsLoaded, canConfigure, router]);

  if (grantsLoaded && !canConfigure) return null;
  if (!tenantId) return null;

  return <OnboardingWizard tenantId={tenantId} />;
}

export default function OnboardResumePage() {
  return (
    <Suspense fallback={null}>
      <OnboardResumeInner />
    </Suspense>
  );
}
