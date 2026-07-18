import type { OrgNodeTreeItem, OrgTreeResponse } from "@/types/api";

// Phase 5i.2 (2026-05-25): shared helper for synthesizing the tenant-
// root row that the backend exposes as sibling fields on
// OrgTreeResponse (tenant_root_id, tenant_root_code, tenant_root_path)
// rather than as the first entry of `tree[]`. Frontend wraps those
// fields into an OrgNodeTreeItem so org-tree consumers can render the
// tenant as the natural top of the hierarchy.
//
// Used by:
//   - components/org/OrgTree.tsx     — /superadmin/org page (5g.1.4)
//   - components/org/OrgNodePicker.tsx — shared tree picker
//
// Always returns a single TENANT-typed root with `tree.tree` as its
// children. For empty tenants (no org structure beyond the root),
// `children = []` and the picker shows just the root — which is a
// valid anchor for tenant-user grants, store creation, and any future
// anchor-required surface. The dead-end "No org nodes configured"
// empty state that used to appear in OrgNodePicker is unreachable
// once consumers route through this helper (Finding #55).
//
// CreateStoreModal uses its own inline `flattenParents` (5h.2) for a
// flat `<select>` rendering and does not consume this helper. The
// concept is the same; the rendering shape differs.

export function synthesizeTenantRoot(
  tree: OrgTreeResponse | undefined,
): OrgNodeTreeItem | null {
  if (!tree) return null;
  const children = tree.tree;
  const fallbackTs =
    children[0]?.created_at ?? new Date(0).toISOString();
  return {
    id: tree.tenant_root_id,
    node_type: "TENANT",
    name: tree.tenant_name,
    code: tree.tenant_root_code,
    status: "ACTIVE",
    created_at: fallbackTs,
    updated_at: children[0]?.updated_at ?? fallbackTs,
    has_children: children.length > 0,
    child_count: children.length,
    loaded_children: "all",
    children,
  };
}
