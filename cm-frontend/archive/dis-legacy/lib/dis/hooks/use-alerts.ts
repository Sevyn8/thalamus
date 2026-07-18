"use client";

import { useQuery } from "@tanstack/react-query";

import { alertsApi } from "@/lib/dis/api/alerts";
import type { AlertEventListParams, AlertRuleListParams } from "@/types/dis";

export function useAlertEvents(params?: AlertEventListParams) {
  return useQuery({
    queryKey: ["dis", "alerts", "events", params],
    queryFn: () => alertsApi.list(params),
  });
}

export function useAlertEvent(id: string) {
  return useQuery({
    queryKey: ["dis", "alerts", "event", id],
    queryFn: () => alertsApi.get(id),
    enabled: !!id,
  });
}

export function useAlertRules(params?: AlertRuleListParams) {
  return useQuery({
    queryKey: ["dis", "alerts", "rules", params],
    queryFn: () => alertsApi.listRules(params),
  });
}

export function useAlertRule(id: string) {
  return useQuery({
    queryKey: ["dis", "alerts", "rule", id],
    queryFn: () => alertsApi.getRule(id),
    enabled: !!id,
  });
}
