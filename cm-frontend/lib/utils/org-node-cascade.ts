import type { OrgNodeType } from "@/types/api";

// Mirrors the backend's _ORDINAL_MAP in
// admin_backend/repositories/org_nodes.py:96-104. A parent's ordinal
// must be STRICTLY lower than the child's. Level-skipping is allowed
// (e.g., BUSINESS_UNIT directly to STORE is legal). TENANT (ordinal
// 0) is excluded from any UI-pickable list — tenant roots are
// auto-provisioned at tenant creation per Step 6.20.1 and are not
// rendered in /superadmin/org's tree.
export const NODE_TYPE_ORDINAL: Record<OrgNodeType, number> = {
  TENANT: 0,
  BUSINESS_UNIT: 1,
  HQ: 2,
  COUNTRY: 3,
  REGION: 4,
  STORE: 5,
  DEPARTMENT: 6,
};

export const ASSIGNABLE_NODE_TYPES: readonly OrgNodeType[] = [
  "BUSINESS_UNIT",
  "HQ",
  "COUNTRY",
  "REGION",
  "STORE",
  "DEPARTMENT",
];

export const NODE_TYPE_LABEL: Record<OrgNodeType, string> = {
  TENANT: "Tenant",
  BUSINESS_UNIT: "Business Unit",
  HQ: "HQ",
  COUNTRY: "Country",
  REGION: "Region",
  STORE: "Store",
  DEPARTMENT: "Department",
};

// Backend regex from OrgNodeCreateRequest.code:
// `^[A-Za-z0-9]([A-Za-z0-9-]{0,62}[A-Za-z0-9])?$`
export const CODE_PATTERN =
  "^[A-Za-z0-9]([A-Za-z0-9-]{0,62}[A-Za-z0-9])?$";
export const CODE_REGEX = new RegExp(CODE_PATTERN);
