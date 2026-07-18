"use client";

import { useCallback, useMemo, useState } from "react";

// Phase 5h.1 (2026-05-21): generic cursor-pagination state helper.
// Backend's CursorPagination shape (next_cursor / prev_cursor /
// has_more / limit) is the source of truth for forward navigation;
// the spec calls prev_cursor "a future affordance" and currently
// returns null on every page. This hook backfills client-side back
// navigation by stacking the cursors used to reach each visited
// page: pushing on next, popping on prev.
//
// Stack representation: `history` always contains at least one
// entry — `undefined` for the initial page (no `cursor` qs param).
// `cursor` returned to the caller is `history[history.length - 1]`,
// passed straight into the api client. `canGoPrev` is true iff
// `history.length > 1`. `canGoNext` is owned by the caller (derived
// from the response's `has_more`).
//
// Reset wipes the stack — used when filters change so cursors
// computed under one filter set don't bleed into another.

export type CursorPaginationState = {
  cursor: string | undefined;
  canGoPrev: boolean;
  goNext: (nextCursor: string | null | undefined) => void;
  goPrev: () => void;
  reset: () => void;
};

export function useCursorPagination(): CursorPaginationState {
  const [history, setHistory] = useState<(string | undefined)[]>([undefined]);

  const cursor = history[history.length - 1];
  const canGoPrev = history.length > 1;

  const goNext = useCallback(
    (nextCursor: string | null | undefined) => {
      if (!nextCursor) return;
      setHistory((prev) => [...prev, nextCursor]);
    },
    [],
  );

  const goPrev = useCallback(() => {
    setHistory((prev) => (prev.length > 1 ? prev.slice(0, -1) : prev));
  }, []);

  const reset = useCallback(() => {
    setHistory([undefined]);
  }, []);

  return useMemo(
    () => ({ cursor, canGoPrev, goNext, goPrev, reset }),
    [cursor, canGoPrev, goNext, goPrev, reset],
  );
}
