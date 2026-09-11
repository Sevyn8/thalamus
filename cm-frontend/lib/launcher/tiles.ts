import {
  Apple,
  Database,
  LineChart,
  Megaphone,
  ShieldCheck,
  Tag,
  Target,
  TriangleAlert,
  Users,
  type LucideIcon,
} from "lucide-react";

import type { ModuleCode } from "@/types/api";

// Launcher tile registry. Eight entries: Admin + DIS as products with
// real routes, 4 product modules matching the module-access enum, plus
// 2 forward-looking placeholders (Insights, Workforce) that are always
// Coming Soon.
//
// Visibility resolution lives in lib/launcher/visibility.ts; this
// file only declares shape + display config.
//
// ===========================================================================
// THE REGISTRY IS KEYED BY MODULE CODE, AND THAT IS THE GUARD
// ===========================================================================
// A flat array where each entry carries a `moduleCode` field has nothing
// checking that the set of those fields covers `ModuleCode`; a module granted
// to a tenant and missing from this file would render NOTHING and report
// NOTHING (getVisibleTiles would silently drop it).
//
// PRODUCT_TILES is a `Record<ModuleCode, ...>`, so the COMPILER refuses a missing
// key and refuses an unknown one. `next build` typechecks, so that is a build
// failure rather than a convention.
//
// TWO THINGS THIS DOES NOT COVER, which is why it is not the only guard:
//   1. A type is defeated by a reformat that adds `as any`, or by anyone turning
//      on typescript.ignoreBuildErrors. scripts/assert-launcher-tiles.mjs asserts
//      the same fact against the ARTIFACT rather than the intent.
//   2. `ModuleCode` is a hand-maintained union and module access is DATA. The
//      server can return a module_code this union has never heard of, and no
//      compile-time check can see that. visibility.ts handles it at runtime.

export type LauncherTileId =
  | "admin"
  | "dis"
  | "pricing-os"
  | "goal-console"
  | "perishables"
  | "promotions"
  | "insights"
  | "workforce";

export type LauncherTileConfig = {
  id: LauncherTileId | string;
  name: string;
  description: string;
  icon: LucideIcon;
  // The available-state route. null for tiles that have no real
  // surface yet (always Coming Soon regardless of persona / matrix).
  href: string | null;
  // The module_code that gates this tile for TENANT personas.
  // null means "not gated by module-access": see PLACEHOLDER_TILES, which is
  // the only place such a tile may be declared.
  moduleCode: ModuleCode | null;
};

// Everything except the module code, which is injected from the key below so the
// two cannot disagree: there is no `moduleCode:` literal in the product entries,
// because a key and a field saying the same thing is a pair that can drift.
type ProductTileConfig = Omit<LauncherTileConfig, "moduleCode">;

const PRODUCT_TILES: Record<ModuleCode, ProductTileConfig> = {
  ADMIN: {
    id: "admin",
    name: "Admin",
    description: "Manage tenants, users, roles, and platform configuration.",
    icon: ShieldCheck,
    href: "/superadmin/dashboard",
  },
  DIS: {
    id: "dis",
    name: "DIS",
    description: "Data ingestion stack: sources, runs, validation, and recovery.",
    icon: Database,
    href: "https://dis-ui-ver2-697546531605.asia-south1.run.app",
  },
  PRICING_OS: {
    id: "pricing-os",
    name: "Pricing OS",
    description: "Price intelligence, promotions guardrails, and competitive monitoring.",
    icon: Tag,
    href: null,
  },
  GOAL_CONSOLE: {
    id: "goal-console",
    name: "Goal Console",
    description: "Set, track, and review store-level KPIs and targets.",
    icon: Target,
    href: null,
  },
  PERISHABLES_ASSISTANT: {
    id: "perishables",
    name: "Perishables Assistant",
    description: "Shrink reduction and markdown recommendations for perishable categories.",
    icon: Apple,
    href: null,
  },
  PROMOTIONS_ASSISTANT: {
    id: "promotions",
    name: "Promotions Assistant",
    description: "Plan, schedule, and measure promotional campaigns across stores.",
    icon: Megaphone,
    href: null,
  },
};

// THE ONLY LEGITIMATE HOME FOR moduleCode: null. A tile here is a DECLARED
// INTENT: a forward-looking placeholder that is not on any tenant's per-module
// contract and is uniformly Coming Soon. It is not a module that lost its tile.
//
// Keeping the two kinds in separate arrays is what makes the distinction
// structural. With one flat array, a single `return []` in visibility.ts would
// mean both "this is a placeholder, correctly hidden" and "this module has no
// tile, silently dropped", and the reader could not tell them apart.
const PLACEHOLDER_TILES: LauncherTileConfig[] = [
  {
    id: "insights",
    name: "Insights",
    description: "Cross-module analytics and intelligence over canonical transaction data.",
    icon: LineChart,
    href: null,
    moduleCode: null,
  },
  {
    id: "workforce",
    name: "Workforce",
    description: "Labor planning, scheduling, and store-associate operations.",
    icon: Users,
    href: null,
    moduleCode: null,
  },
];

// Object.entries widens the key to `string`, which is a known TypeScript
// limitation rather than a real loosening: the Record type above is what
// guarantees the keys are exactly ModuleCode, and the cast restates it.
export const LAUNCHER_TILES: LauncherTileConfig[] = [
  ...Object.entries(PRODUCT_TILES).map(([code, tile]) => ({
    ...tile,
    moduleCode: code as ModuleCode,
  })),
  ...PLACEHOLDER_TILES,
];

// The tile shown for a module the server says is enabled and this build has no
// entry for. It is deliberately NOT a silent omission and deliberately NOT a
// plausible-looking product card: it names the code, because the code is the
// only true thing available and it is what somebody will need in order to fix it.
//
// See visibility.ts for why this case is reachable at all despite the compiler
// check above: module access is data, and a hand-maintained union cannot
// constrain what a server returns.
export function unmappedTile(moduleCode: string): LauncherTileConfig {
  return {
    id: `unmapped-${moduleCode}`,
    name: moduleCode,
    description:
      "This workspace is enabled for your organisation, but this version of the console " +
      "has no page for it. Nothing is wrong with your access. Report the code above to " +
      "your administrator.",
    icon: TriangleAlert,
    href: null,
    moduleCode: null,
  };
}
