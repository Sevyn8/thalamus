"use client";

import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { MotionConfig } from "framer-motion";

import { TooltipProvider } from "@/components/ui/tooltip";

// Phase 5n.1 (2026-05-18): MSW removed wholesale. No worker.start(),
// no __msw_overrides, no __test_query window augmentation. All fetches
// go directly to NEXT_PUBLIC_API_BASE_URL per lib/api/client.ts. The
// app is no longer gated on an MSW-ready flag — Providers renders
// children immediately.

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  });
}

let browserQueryClient: QueryClient | undefined;

function getQueryClient(): QueryClient {
  if (typeof window === "undefined") return makeQueryClient();
  if (!browserQueryClient) {
    browserQueryClient = makeQueryClient();
  }
  return browserQueryClient;
}

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => getQueryClient());

  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      storageKey="ithina-theme"
      disableTransitionOnChange
    >
      <MotionConfig reducedMotion="user">
        <TooltipProvider delay={500}>
          <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        </TooltipProvider>
      </MotionConfig>
    </ThemeProvider>
  );
}
