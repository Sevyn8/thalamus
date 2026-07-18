"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { templatesApi } from "@/lib/dis/api/templates";
import type {
  CreateTemplateInput,
  TemplateListParams,
  UpdateTemplateInput,
} from "@/types/dis";

export function useTemplates(params?: TemplateListParams) {
  return useQuery({
    queryKey: ["dis", "templates", params],
    queryFn: () => templatesApi.list(params),
  });
}

export function useTemplate(id: string) {
  return useQuery({
    queryKey: ["dis", "template", id],
    queryFn: () => templatesApi.get(id),
    enabled: !!id,
  });
}

export function useCreateTemplate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateTemplateInput) => templatesApi.create(input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dis", "templates"] });
    },
  });
}

export function useUpdateTemplate(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: UpdateTemplateInput) => templatesApi.update(id, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dis", "templates"] });
      qc.invalidateQueries({ queryKey: ["dis", "template", id] });
    },
  });
}
