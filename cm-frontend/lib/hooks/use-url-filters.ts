"use client";

import { useCallback, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";

// Canonical filter-state ↔ URL contract for list surfaces: a shared
// hook that round-trips filter state through the URL instead of
// per-surface `useState<XFiltersState>`.
//
// Behavior:
//   - Reads URL params during render (no useEffect → no flicker on
//     mount; React 19 supports this cleanly).
//   - Returns [filters, setFilters] mirroring useState's tuple so
//     drop-in replacement is one line per surface.
//   - setFilters serializes the diff-from-defaults to the URL.
//     Values equal to their default are STRIPPED so default state
//     produces a bare URL (`/dis/alerts`, not
//     `/dis/alerts?state=all&severity=all&...`). Keeps URLs
//     scannable + shareable.
//   - router.replace (not push) — filter changes don't add history
//     entries. Browser back/forward + reload still preserve state
//     because URL is the source of truth.
//
// Persona-aware tenant_id behavior lives at the API-call layer, NOT
// here. The hook is persona-agnostic; it round-trips whatever the URL
// says.
//
// Typed as Record<string, string> — all current filter states are
// string-based ("all" sentinels, tenant_id strings, search strings).
// If a future surface needs number / boolean filters, extend the hook
// (serialize / parse via JSON or per-key codecs).

export function useUrlFilters<T extends Record<string, string>>(
  defaults: T,
  routePath: string,
): [T, (next: T) => void] {
  const router = useRouter();
  const searchParams = useSearchParams();

  const filters = useMemo<T>(() => {
    const out = { ...defaults };
    for (const key of Object.keys(defaults) as (keyof T)[]) {
      const param = searchParams.get(key as string);
      if (param !== null) {
        out[key] = param as T[keyof T];
      }
    }
    return out;
  }, [defaults, searchParams]);

  const setFilters = useCallback(
    (next: T) => {
      const sp = new URLSearchParams(searchParams.toString());
      for (const key of Object.keys(defaults) as (keyof T)[]) {
        const value = next[key];
        // Strip keys whose value matches the default to keep URLs
        // bare for the no-filter case.
        if (value === defaults[key]) {
          sp.delete(key as string);
        } else {
          sp.set(key as string, value as string);
        }
      }
      const qs = sp.toString();
      router.replace(`${routePath}${qs ? `?${qs}` : ""}`);
    },
    [defaults, routePath, router, searchParams],
  );

  return [filters, setFilters];
}
