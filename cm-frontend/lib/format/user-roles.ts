// Shared role-list formatter for users tables.
// Filters to ACTIVE assignments + dedupes by role_name so a user with
// multiple anchors under the same role doesn't display the role twice.
// Returns:
//   0 unique active roles  → "—"
//   1 unique active role   → "{role_name}"
//   N>1 unique active roles → "{first_role_name} +{N-1} more"

type RoleAssignmentLike = {
  role_name: string;
  status: string;
};

export function formatUserRoles(roles: readonly RoleAssignmentLike[] | undefined): string {
  if (!roles || roles.length === 0) return "—";
  const activeNames = roles
    .filter((r) => r.status === "ACTIVE")
    .map((r) => r.role_name);
  const unique = Array.from(new Set(activeNames));
  if (unique.length === 0) return "—";
  if (unique.length === 1) return unique[0]!;
  return `${unique[0]} +${unique.length - 1} more`;
}
