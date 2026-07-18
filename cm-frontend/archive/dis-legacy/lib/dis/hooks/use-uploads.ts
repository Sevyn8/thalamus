"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { uploadsApi } from "@/lib/dis/api/uploads";
import type { ConfirmMappingInput, UploadListParams } from "@/types/dis";

export function useUploads(params?: UploadListParams) {
  return useQuery({
    queryKey: ["dis", "uploads", params],
    queryFn: () => uploadsApi.list(params),
  });
}

export function useUpload(id: string) {
  return useQuery({
    queryKey: ["dis", "upload", id],
    queryFn: () => uploadsApi.get(id),
    enabled: !!id,
  });
}

export function useCreateUpload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, templateId }: { file: File; templateId?: string | null }) =>
      uploadsApi.create(file, templateId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dis", "uploads"] });
    },
  });
}

export function useConfirmMapping(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: ConfirmMappingInput) => uploadsApi.confirmMapping(id, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dis", "uploads"] });
      qc.invalidateQueries({ queryKey: ["dis", "upload", id] });
    },
  });
}
