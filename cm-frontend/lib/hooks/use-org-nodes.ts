"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  orgNodesApi,
  type OrgNodeCreatePayload,
  type OrgNodePatchPayload,
} from "@/lib/api/org-nodes";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import type {
  OrgNodeChildrenResponse,
  OrgNodeTreeItem,
} from "@/types/api";

// Initial-fetch depth. Matches the existing OrgTree component's
// "top 2 levels visible by default" UX (depth 0 + 1). Backend caps
// at 6 with auto-truncation past 1000 nodes — depth=2 well under
// the cap for the dev seed.
const DEFAULT_DEPTH = 2;

// Phase 5h.1.1 (2026-05-21): userId in queryKey to prevent cross-
// persona cache bleed. For org-tree the response shape for a given
// tenantId is materially the same across viewers (RLS gates access
// at the endpoint, but the tree data itself is tenant-property),
// so this is hygiene rather than a leak; keeping the pattern uniform
// is what matters. See Finding #50.

export function useOrgTree(tenantId: string, depth: number = DEFAULT_DEPTH) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useQuery({
    queryKey: ["org-tree", userId, tenantId, depth],
    queryFn: () => orgNodesApi.tree(tenantId, { depth }),
    enabled: !!userId && !!tenantId,
  });
}

// Lazy children fetcher.
//
// `enabled` controls when the query fires. The OrgTreeRow that owns
// this hook flips it true when (a) the row is expanded AND (b) the
// node has children that aren't all in the initial tree response
// (loaded_children !== "all"). Otherwise it stays disabled and TQ
// doesn't fetch.
//
// Lifecycle policy (per Phase 4e plan):
//   - Collapse: `enabled` flips false; cached pages stay in TQ
//     cache. Re-expand reads from cache, no re-fetch.
//   - Tenant switch: tenantId is in the queryKey, so cross-tenant
//     queries are isolated. The OrgTreePane is also re-keyed on
//     tenantId so its component state resets and old queries gc.
//   - "+N more" pagination: fetchNextPage uses initialPageParam +
//     getNextPageParam; results accumulate in `data.pages` (TQ is
//     the single source of truth — no separate Map needed).
//
// `initialOffset` should be node.children.length when
// loaded_children === "partial" (initial tree already gave us some;
// fetch starts at the next offset), else 0 ("none" — fetch from
// the start since none came in the initial tree).
export function useOrgNodeChildren(
  tenantId: string,
  nodeId: string,
  enabled: boolean,
  initialOffset: number = 0,
  pageSize: number = 100,
) {
  const userId = useAuthSnapshot()?.user?.userId ?? null;
  return useInfiniteQuery<OrgNodeChildrenResponse>({
    queryKey: [
      "org-children",
      userId,
      tenantId,
      nodeId,
      initialOffset,
      pageSize,
    ],
    queryFn: ({ pageParam }) =>
      orgNodesApi.children(tenantId, nodeId, {
        offset: pageParam as number,
        limit: pageSize,
      }),
    enabled: enabled && !!userId && !!tenantId && !!nodeId,
    initialPageParam: initialOffset,
    getNextPageParam: (lastPage) => {
      const { offset, limit, total } = lastPage.pagination;
      const next = offset + limit;
      return next < total ? next : undefined;
    },
  });
}

// Flatten useInfiniteQuery pages into a single OrgNodeTreeItem[] for
// rendering. Returns [] when the query hasn't run or has no pages.
export function flattenChildPages(
  data: { pages: OrgNodeChildrenResponse[] } | undefined,
): OrgNodeTreeItem[] {
  if (!data) return [];
  return data.pages.flatMap((p) => p.items);
}

// Phase 5n.7 write hooks. Server-wait per the post-MSW canonical
// pattern (Finding #32). `invalidateQueries` covers both the initial
// tree fetch and any lazy-loaded child page caches for the affected
// tenant. On reparent (PATCH with parent_id), the old-parent's child
// listing also needs to drop the moved node, but a tenant-wide
// org-tree invalidate is the simplest and cheapest correct choice
// (one extra ~few-hundred-ms fetch beats tracking the prior parent
// inside the mutation closure).

function invalidateOrgTree(
  queryClient: ReturnType<typeof useQueryClient>,
  tenantId: string,
): void {
  void queryClient.invalidateQueries({ queryKey: ["org-tree", tenantId] });
  void queryClient.invalidateQueries({ queryKey: ["org-children", tenantId] });
}

export function useCreateOrgNode(tenantId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: OrgNodeCreatePayload) =>
      orgNodesApi.create(tenantId, input),
    onSuccess: () => invalidateOrgTree(queryClient, tenantId),
  });
}

export function useEditOrgNode(tenantId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      nodeId,
      patch,
    }: {
      nodeId: string;
      patch: OrgNodePatchPayload;
    }) => orgNodesApi.patch(tenantId, nodeId, patch),
    onSuccess: () => invalidateOrgTree(queryClient, tenantId),
  });
}
