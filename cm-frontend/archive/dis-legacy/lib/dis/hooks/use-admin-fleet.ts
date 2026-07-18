"use client";

import { useQuery } from "@tanstack/react-query";

import { adminFleetApi } from "@/lib/dis/api/admin-fleet";

export function useFleetHealth() {
  return useQuery({
    queryKey: ["dis", "admin", "fleet"],
    queryFn: adminFleetApi.health,
  });
}
