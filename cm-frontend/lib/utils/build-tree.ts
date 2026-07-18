import type { OrgNodeTreeItem } from "@/types/api";

// Backend's OrgTreeResponse.tree is already nested via OrgNodeTreeItem.children;
// no flat-to-nested assembly is needed (the old buildTree() helper retired
// when the backend wire landed in Phase 4e). The helpers below operate on
// the recursive shape for tree-walks (find a node by id; count subtree size
// for the detail drawer's "X in subtree" badge).

export function findNode(
  roots: OrgNodeTreeItem[],
  id: string,
): OrgNodeTreeItem | null {
  for (const r of roots) {
    if (r.id === id) return r;
    const found = findNode(r.children ?? [], id);
    if (found) return found;
  }
  return null;
}

export function countSubtree(node: OrgNodeTreeItem): number {
  const children = node.children ?? [];
  let total = children.length;
  for (const c of children) total += countSubtree(c);
  return total;
}
