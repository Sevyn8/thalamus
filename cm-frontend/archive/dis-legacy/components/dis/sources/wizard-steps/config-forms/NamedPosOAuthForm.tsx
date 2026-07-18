"use client";

import { useId } from "react";
import { Plug } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { ConnectionConfig, Environment } from "@/types/dis";

// Phase 5c.2b2: shared form for the 4 named POS connectors that
// share an identifier-only shape (Square / Lightspeed / Toast /
// Clover). Shopify POS has a different shape (shop_domain only) so
// it gets its own form. Per A2 amendment: the disabled "Connect with
// [brand]" button is the visual primary; identifier inputs are
// labeled as v1 workaround for the missing OAuth round-trip.
//
// Real-world flow for these connectors is OAuth-first; identifiers
// come AFTER authorization. v1 collects identifiers as a placeholder
// for the demo, with explicit messaging that production reverses
// the order. This UX choice avoids misrepresenting the connection
// model in design walkthroughs.

type Variant = "SQUARE" | "LIGHTSPEED" | "TOAST" | "CLOVER";

// Field names are runtime-string keys into the variant's
// connection_config shape. Intersecting with keyof ConnectionConfig
// would collapse to just "type" (the only key shared across all
// union variants), so the spec uses plain string for the field
// names. Variant-correctness is enforced by the SPECS literal below.
type FieldSpec = {
  brandLabel: string;
  primaryFieldName: string;
  primaryFieldLabel: string;
  primaryFieldPlaceholder: string;
  secondaryFieldName?: string;
  secondaryFieldLabel?: string;
  secondaryFieldPlaceholder?: string;
};

const SPECS: Record<Variant, FieldSpec> = {
  SQUARE: {
    brandLabel: "Square",
    primaryFieldName: "merchant_id",
    primaryFieldLabel: "Merchant ID",
    primaryFieldPlaceholder: "MLAGTV9X8RKKK",
    secondaryFieldName: "location_id",
    secondaryFieldLabel: "Location ID",
    secondaryFieldPlaceholder: "L7K3RT2H8",
  },
  LIGHTSPEED: {
    brandLabel: "Lightspeed",
    primaryFieldName: "account_id",
    primaryFieldLabel: "Account ID",
    primaryFieldPlaceholder: "ls-3014772",
  },
  TOAST: {
    brandLabel: "Toast",
    primaryFieldName: "restaurant_guid",
    primaryFieldLabel: "Restaurant GUID",
    primaryFieldPlaceholder: "5e8a-4f2b-9c1d-3a7e",
  },
  CLOVER: {
    brandLabel: "Clover",
    primaryFieldName: "merchant_id",
    primaryFieldLabel: "Merchant ID",
    primaryFieldPlaceholder: "BUCEES-CLOVER-001",
  },
};

type Props = {
  variant: Variant;
  value: Partial<ConnectionConfig>;
  onChange: (next: Partial<ConnectionConfig>, valid: boolean) => void;
};

export function NamedPosOAuthForm({ variant, value, onChange }: Props) {
  const spec = SPECS[variant];
  const v = value as Record<string, unknown>;
  const primary = (v[spec.primaryFieldName] as string | undefined) ?? "";
  const secondary = spec.secondaryFieldName
    ? ((v[spec.secondaryFieldName] as string | undefined) ?? "")
    : "";
  const environment = (v.environment as Environment | undefined) ?? "production";
  const primaryId = useId();
  const secondaryId = useId();
  const environmentId = useId();

  function update(patch: Record<string, unknown>) {
    const merged = { ...value, type: variant, environment, ...patch };
    const mergedAsRecord = merged as unknown as Record<string, unknown>;
    const primaryFilled = String(mergedAsRecord[spec.primaryFieldName] ?? "").trim().length > 0;
    const secondaryFilled = spec.secondaryFieldName
      ? String(mergedAsRecord[spec.secondaryFieldName] ?? "").trim().length > 0
      : true;
    const valid = primaryFilled && secondaryFilled;
    onChange(merged, valid);
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2 rounded-md border border-border bg-card/30 p-4">
        <Tooltip>
          <TooltipTrigger
            render={
              <span tabIndex={0} className="inline-flex w-fit">
                <Button disabled aria-disabled="true">
                  <Plug className="h-4 w-4" />
                  Connect with {spec.brandLabel}
                </Button>
              </span>
            }
          />
          <TooltipContent>
            OAuth flow lands in Phase 5d.
          </TooltipContent>
        </Tooltip>
        <p className="text-caption text-muted-foreground">
          OAuth flow lands in Phase 5d. v1 stubs authorization for demo
          purposes.
        </p>
      </div>

      <div className="flex flex-col gap-3">
        <p className="text-caption text-muted-foreground">
          These will be auto-populated post-OAuth in production. v1 collects
          them manually so the demo can proceed.
        </p>

        <div className="flex flex-col gap-2">
          <label htmlFor={primaryId} className="text-label text-muted-foreground">
            {spec.primaryFieldLabel}
          </label>
          <Input
            id={primaryId}
            type="text"
            value={primary}
            placeholder={spec.primaryFieldPlaceholder}
            onChange={(e) => update({ [spec.primaryFieldName]: e.target.value })}
          />
        </div>

        {spec.secondaryFieldName && spec.secondaryFieldLabel ? (
          <div className="flex flex-col gap-2">
            <label htmlFor={secondaryId} className="text-label text-muted-foreground">
              {spec.secondaryFieldLabel}
            </label>
            <Input
              id={secondaryId}
              type="text"
              value={secondary}
              placeholder={spec.secondaryFieldPlaceholder}
              onChange={(e) =>
                update({ [spec.secondaryFieldName!]: e.target.value })
              }
            />
          </div>
        ) : null}

        <div className="flex flex-col gap-2">
          <label htmlFor={environmentId} className="text-label text-muted-foreground">
            Environment
          </label>
          <select
            id={environmentId}
            value={environment}
            onChange={(e) => update({ environment: e.target.value as Environment })}
            className="h-9 rounded-md border border-input bg-background px-2.5 py-1 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none dark:bg-input/30"
          >
            <option value="sandbox">Sandbox</option>
            <option value="production">Production</option>
          </select>
        </div>
      </div>
    </div>
  );
}
