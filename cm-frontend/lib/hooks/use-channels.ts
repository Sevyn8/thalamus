"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { channelsApi, type ChannelUpsertRequest } from "@/lib/api/channels";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";

// react-query hooks for tenant sending channels. Server-wait pattern (no
// optimistic state), invalidateQueries on success — same convention as
// use-stores.ts.
//
// userId IS IN EVERY QUERY KEY (prevents cross-persona cache bleed). It
// matters more here than elsewhere: the tenant read and the operator read hit
// two different endpoints whose rows describe different tenants, and a persona
// switch that reused a cached entry would show one tenant's connection state
// under another tenant's heading.
//
// NOTHING CACHED HERE IS A CREDENTIAL. Both endpoints return connection state
// and the secret's NAME. The credential exists only in the form's own state
// between typing and submit, and the form clears it on success.

export function useMyChannels(options?: { enabled?: boolean }) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["channels", "mine", userId],
    queryFn: () => channelsApi.mine(),
    // The caller decides. The page passes false for any caller it will not
    // render the surface to, so a PLATFORM persona never fires this request.
    // See the guard in app/my-sevyn8/channels/page.tsx for why that is not
    // merely tidy: GET /channels has no audience pin, and under a PLATFORM
    // session RLS returns EVERY tenant's rows from it.
    enabled: options?.enabled ?? true,
  });
}

export function usePlatformChannels(options?: { enabled?: boolean }) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["channels", "platform", userId],
    queryFn: () => channelsApi.platform(),
    enabled: options?.enabled ?? true,
  });
}

export function useUpsertChannel() {
  const queryClient = useQueryClient();
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useMutation({
    mutationFn: (input: ChannelUpsertRequest) => channelsApi.upsert(input),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["channels", "mine", userId],
      });
    },
  });
}
