"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { tenantsApi } from "@/lib/api/tenants";
import { tenantUsersApi } from "@/lib/api/tenant-users";

// Hooks for the Auth0 provisioning + invitation endpoints.
// Server-wait mutations (no optimistic UI), matching the codebase
// convention.

// Provisioning the tenant Auth0 org stamps tenants.auth0_org_id
// (backend option a), so the onboarding-state auth0_organization fact
// flips to TRUE -> invalidate onboarding-state.
export function useProvisionTenantAuth0(tenantId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => tenantsApi.provisionAuth0(tenantId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["onboarding-state"] });
    },
  });
}

// Provisioning a user's Auth0 identity writes nothing to CM, so there is
// no cache to invalidate; the result is consumed transiently by the
// sequence. (Kept as a hook for consistency + error handling.)
export function useProvisionTenantUserAuth0() {
  return useMutation({
    mutationFn: (userId: string) => tenantUsersApi.provisionAuth0(userId),
  });
}

// Sending the invitation sets invited_at, which drives the per-user
// status derivation -> invalidate the tenant-users list.
export function useSendInvitation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => tenantUsersApi.sendInvitation(userId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenant-users"] });
    },
  });
}
