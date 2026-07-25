"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { onboardingApi } from "@/lib/api/onboarding";
import { tenantsApi } from "@/lib/api/tenants";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import type {
  BillingProfileUpsertRequest,
  ContactsReplaceRequest,
  LegalProfileUpsertRequest,
  OnboardingPatchRequest,
  TaxRegistrationsReplaceRequest,
} from "@/types/api";

// Onboarding wizard hooks. Server-wait mutations (no optimistic UI),
// matching the tenants convention. Query keys carry userId to prevent
// cross-persona cache bleed (Phase 5h.1.1 precedent). Section writes
// invalidate BOTH the section query and the onboarding-state query,
// because the step rail reads presence flags + section_status from state.

function useUserId(): string | null {
  return useAuthSnapshot()?.user?.userId ?? null;
}

export function useOnboardingState(tenantId: string | null) {
  const userId = useUserId();
  return useQuery({
    queryKey: ["onboarding-state", userId, tenantId],
    queryFn: () => onboardingApi.getState(tenantId as string),
    enabled: !!userId && !!tenantId,
  });
}

export function useLegalProfile(tenantId: string | null) {
  const userId = useUserId();
  return useQuery({
    queryKey: ["onboarding-legal", userId, tenantId],
    queryFn: () => onboardingApi.getLegalProfile(tenantId as string),
    enabled: !!userId && !!tenantId,
  });
}

export function useTaxRegistrations(tenantId: string | null) {
  const userId = useUserId();
  return useQuery({
    queryKey: ["onboarding-tax", userId, tenantId],
    queryFn: () => onboardingApi.getTaxRegistrations(tenantId as string),
    enabled: !!userId && !!tenantId,
  });
}

export function useBillingProfile(tenantId: string | null) {
  const userId = useUserId();
  return useQuery({
    queryKey: ["onboarding-billing", userId, tenantId],
    queryFn: () => onboardingApi.getBillingProfile(tenantId as string),
    enabled: !!userId && !!tenantId,
  });
}

export function useContacts(tenantId: string | null) {
  const userId = useUserId();
  return useQuery({
    queryKey: ["onboarding-contacts", userId, tenantId],
    queryFn: () => onboardingApi.getContacts(tenantId as string),
    enabled: !!userId && !!tenantId,
  });
}

// Prefix-match invalidation covers the userId-scoped keys without knowing
// the active userId at call time (["onboarding-state"] matches
// ["onboarding-state", userId, tenantId]).
function invalidateState(
  qc: ReturnType<typeof useQueryClient>,
): void {
  void qc.invalidateQueries({ queryKey: ["onboarding-state"] });
}

export function usePutLegalProfile(tenantId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: LegalProfileUpsertRequest) =>
      onboardingApi.putLegalProfile(tenantId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["onboarding-legal"] });
      invalidateState(qc);
    },
  });
}

export function usePutTaxRegistrations(tenantId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: TaxRegistrationsReplaceRequest) =>
      onboardingApi.putTaxRegistrations(tenantId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["onboarding-tax"] });
      invalidateState(qc);
    },
  });
}

export function usePutBillingProfile(tenantId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: BillingProfileUpsertRequest) =>
      onboardingApi.putBillingProfile(tenantId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["onboarding-billing"] });
      invalidateState(qc);
    },
  });
}

export function usePutContacts(tenantId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ContactsReplaceRequest) =>
      onboardingApi.putContacts(tenantId, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["onboarding-contacts"] });
      invalidateState(qc);
    },
  });
}

export function usePatchOnboardingState(tenantId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: OnboardingPatchRequest) =>
      onboardingApi.patchState(tenantId, body),
    onSuccess: () => invalidateState(qc),
  });
}

// Slice 6: complete onboarding (ONBOARDING -> TRIAL). Invalidates the
// tenant list + detail + onboarding-state so the drawer/list reflect TRIAL.
export function useCompleteOnboarding(tenantId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => tenantsApi.completeOnboarding(tenantId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tenants"] });
      // Slice 7 item 5: ["tenant"] prefix (not ["tenant", tenantId]) so the
      // per-user detail key ["tenant", userId, id] is matched -> drawer
      // shows TRIAL immediately after complete-onboarding.
      void qc.invalidateQueries({ queryKey: ["tenant"] });
      invalidateState(qc);
    },
  });
}
