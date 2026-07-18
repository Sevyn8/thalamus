"use client";

import { useQuery } from "@tanstack/react-query";

import { lookupsApi } from "@/lib/api/lookups";

export function useLookups() {
  return useQuery({
    queryKey: ["lookups"],
    queryFn: lookupsApi.all,
    staleTime: 60 * 60_000,
  });
}
