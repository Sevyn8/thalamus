"use client";

import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  canonicalSchemaApi,
  type CanonicalSchemaFieldUpdateInput,
} from "@/lib/dis/api/canonical-schema";
import type {
  CanonicalSchemaDomain,
  CanonicalSchemaField,
  CanonicalSchemaFieldCreateInput,
  CanonicalSchemaVersionBumpInput,
} from "@/types/dis";

export function useCanonicalSchema() {
  return useQuery({
    queryKey: ["dis", "canonical-schema"],
    queryFn: () => canonicalSchemaApi.list(),
    // Canonical schema rarely changes during a session; longer staleTime
    // avoids a refetch every time the mapping-review surface mounts.
    staleTime: 5 * 60_000,
  });
}

// Phase 5c.7a: derived selectors over the full schema. No new MSW
// endpoints — the existing list returns ~30 fields total, so client-
// side lookup is cheaper than per-resource HTTP. useMemo prevents
// re-derivation on unrelated re-renders.

export function useCanonicalDomain(domainId: string): {
  isLoading: boolean;
  error: unknown;
  data: CanonicalSchemaDomain | undefined;
} {
  const query = useCanonicalSchema();
  const data = useMemo(
    () => query.data?.domains.find((d) => d.id === domainId),
    [query.data, domainId],
  );
  return { isLoading: query.isLoading, error: query.error, data };
}

export function useCanonicalField(
  domainId: string,
  fieldId: string,
): {
  isLoading: boolean;
  error: unknown;
  domain: CanonicalSchemaDomain | undefined;
  field: CanonicalSchemaField | undefined;
} {
  const query = useCanonicalSchema();
  const { domain, field } = useMemo(() => {
    const d = query.data?.domains.find((x) => x.id === domainId);
    const f = d?.fields.find((x) => x.id === fieldId);
    return { domain: d, field: f };
  }, [query.data, domainId, fieldId]);
  return { isLoading: query.isLoading, error: query.error, domain, field };
}

// Phase 5c.8b1: PATCH a canonical field. Invalidates the schema
// query on success so consumers (admin domain detail + read view)
// re-render with the new values.
export function useUpdateCanonicalField() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: {
      domainId: string;
      fieldId: string;
      input: CanonicalSchemaFieldUpdateInput;
    }) => canonicalSchemaApi.updateField(args.domainId, args.fieldId, args.input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["dis", "canonical-schema"] });
    },
  });
}

// Phase 5c.8b2: POST a new canonical field. Same invalidation
// pattern as useUpdateCanonicalField.
export function useAddCanonicalField() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: {
      domainId: string;
      input: CanonicalSchemaFieldCreateInput;
    }) => canonicalSchemaApi.addField(args.domainId, args.input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["dis", "canonical-schema"] });
    },
  });
}

// Phase 5c.8b2: POST bump domain version.
export function useBumpCanonicalVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: {
      domainId: string;
      input: CanonicalSchemaVersionBumpInput;
    }) => canonicalSchemaApi.bumpVersion(args.domainId, args.input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["dis", "canonical-schema"] });
    },
  });
}
