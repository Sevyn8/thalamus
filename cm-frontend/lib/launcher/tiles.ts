import {
  Apple,
  Database,
  LineChart,
  Megaphone,
  ShieldCheck,
  Tag,
  Target,
  Users,
  type LucideIcon,
} from "lucide-react";

import type { ModuleCode } from "@/types/api";

// Phase 5d.1: launcher tile registry. Eight entries (post Phase 5e.0
// ROOS retirement): Admin + DIS as products with real routes (when
// available), 4 product modules matching the module-access enum, plus
// 2 forward-looking placeholders (Insights, Workforce) that are always
// Coming Soon in v0.
//
// Visibility resolution lives in lib/launcher/visibility.ts — this
// file only declares shape + display config.

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
  id: LauncherTileId;
  name: string;
  description: string;
  icon: LucideIcon;
  // The available-state route. null for tiles that have no real
  // surface yet (always Coming Soon regardless of persona / matrix).
  href: string | null;
  // The module_code that gates this tile for TENANT personas.
  // null means "not gated by module-access" (Admin uses persona type
  // instead; Insights + Workforce are uniformly Coming Soon).
  moduleCode: ModuleCode | null;
};

export const LAUNCHER_TILES: LauncherTileConfig[] = [
  {
    id: "admin",
    name: "Admin",
    description: "Manage tenants, users, roles, and platform configuration.",
    icon: ShieldCheck,
    href: "/superadmin/dashboard",
    moduleCode: "ADMIN",
  },
  {
    id: "dis",
    name: "DIS",
    description: "Data ingestion stack — sources, runs, validation, and recovery.",
    icon: Database,
    href: "https://dis-ui-10292879382.asia-south1.run.app/dev/login",
    moduleCode: "DIS",
  },
  {
    id: "pricing-os",
    name: "Pricing OS",
    description: "Price intelligence, promotions guardrails, and competitive monitoring.",
    icon: Tag,
    href: null,
    moduleCode: "PRICING_OS",
  },
  {
    id: "goal-console",
    name: "Goal Console",
    description: "Set, track, and review store-level KPIs and targets.",
    icon: Target,
    href: null,
    moduleCode: "GOAL_CONSOLE",
  },
  {
    id: "perishables",
    name: "Perishables Assistant",
    description: "Shrink reduction and markdown recommendations for perishable categories.",
    icon: Apple,
    href: null,
    moduleCode: "PERISHABLES_ASSISTANT",
  },
  {
    id: "promotions",
    name: "Promotions Assistant",
    description: "Plan, schedule, and measure promotional campaigns across stores.",
    icon: Megaphone,
    href: null,
    moduleCode: "PROMOTIONS_ASSISTANT",
  },
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
