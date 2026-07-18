// Phase 5n.4: backend not shipped (no /api/v1/notifications endpoint).
// Replace with real hook + list when notifications endpoint ships.

import { PageHeader } from "@/components/shared/PageHeader";
import { FeaturePending } from "@/components/shared/FeaturePending";

export default function NotificationsPage() {
  return (
    <>
      <PageHeader
        title="Notifications"
        subtitle="Alerts from approvals, invites, and tenant lifecycle."
      />
      <FeaturePending surface="Notifications" eta="Admin APIs ~2 days" />
    </>
  );
}
