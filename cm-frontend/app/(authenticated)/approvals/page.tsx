"use client";

import { Inbox } from "lucide-react";

import { PageHeader } from "@/components/shared/PageHeader";
import { EmptyState } from "@/components/shared/EmptyState";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";

export default function ApprovalsPage() {
  // Persona-aware subtitle. PLATFORM sees fleet-wide framing; TENANT
  // sees own-organization framing. Cosmetic — backend scopes the data
  // the same way regardless.
  const snapshot = useAuthSnapshot();
  const subtitle =
    snapshot?.user?.userType === "TENANT"
      ? "Pending approval requests across your organization."
      : "Pending approval requests across all tenants.";
  return (
    <div className="flex flex-col">
      <PageHeader title="Approvals Inbox" subtitle={subtitle} />
      <section className="px-6 py-12">
        <EmptyState
          icon={<Inbox />}
          title="Approvals inbox coming in v1"
          body="Pending approval requests will appear here when wired."
        />
      </section>
    </div>
  );
}
