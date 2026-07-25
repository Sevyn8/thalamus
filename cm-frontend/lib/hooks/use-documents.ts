"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { documentsApi } from "@/lib/api/documents";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import type { DocumentUploadUrlRequest } from "@/types/api";
import type { DocumentRejectRequest } from "@/types/api";

// Documents step hooks. The list is a pure DB read (works without GCS).
// Upload is a two-phase flow orchestrated in the component (create-url ->
// direct PUT); this file exposes the create-url + delete mutations and the
// list query. Deleting invalidates both the list and the onboarding-state
// query (the state's documents block counts must stay in sync).

function useUserId(): string | null {
  return useAuthSnapshot()?.user?.userId ?? null;
}

export function useDocuments(tenantId: string | null) {
  const userId = useUserId();
  return useQuery({
    queryKey: ["documents", userId, tenantId],
    queryFn: () => documentsApi.list(tenantId as string),
    enabled: !!userId && !!tenantId,
  });
}

function invalidateDocuments(
  qc: ReturnType<typeof useQueryClient>,
): void {
  void qc.invalidateQueries({ queryKey: ["documents"] });
  void qc.invalidateQueries({ queryKey: ["onboarding-state"] });
}

export function useCreateUploadUrl(tenantId: string) {
  return useMutation({
    mutationFn: (body: DocumentUploadUrlRequest) =>
      documentsApi.createUploadUrl(tenantId, body),
  });
}

export function useDeleteDocument(tenantId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (documentId: string) =>
      documentsApi.remove(tenantId, documentId),
    onSuccess: () => invalidateDocuments(qc),
  });
}

export function useVerifyDocument(tenantId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (documentId: string) =>
      documentsApi.verify(tenantId, documentId),
    onSuccess: () => invalidateDocuments(qc),
  });
}

export function useRejectDocument(tenantId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      documentId,
      body,
    }: {
      documentId: string;
      body: DocumentRejectRequest;
    }) => documentsApi.reject(tenantId, documentId, body),
    onSuccess: () => invalidateDocuments(qc),
  });
}

export function useDocumentsInvalidate() {
  const qc = useQueryClient();
  return () => invalidateDocuments(qc);
}
