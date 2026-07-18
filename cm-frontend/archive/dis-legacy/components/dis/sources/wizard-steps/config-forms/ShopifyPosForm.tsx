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
import type { ConnectionConfig } from "@/types/dis";

type Props = {
  value: Partial<ConnectionConfig>;
  onChange: (next: Partial<ConnectionConfig>, valid: boolean) => void;
};

// Phase 5c.2b2: Shopify POS form. Single shop_domain field. Same
// OAuth-button-on-top treatment as NamedPosOAuthForm per A2 amendment.
// Format hint nudges tenant toward the correct domain shape; full
// validation happens server-side at test-connection.
export function ShopifyPosForm({ value, onChange }: Props) {
  const v = value as Record<string, unknown>;
  const shopDomain = (v.shop_domain as string | undefined) ?? "";
  const shopDomainId = useId();

  function update(next: string) {
    const merged: Partial<ConnectionConfig> = {
      type: "SHOPIFY_POS",
      shop_domain: next,
    };
    const valid = next.trim().length > 0 && next.trim().endsWith(".myshopify.com");
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
                  Connect with Shopify
                </Button>
              </span>
            }
          />
          <TooltipContent>OAuth flow lands in Phase 5d.</TooltipContent>
        </Tooltip>
        <p className="text-caption text-muted-foreground">
          OAuth flow lands in Phase 5d. v1 stubs authorization for demo purposes.
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor={shopDomainId} className="text-label text-muted-foreground">
          Shop domain
        </label>
        <Input
          id={shopDomainId}
          type="text"
          value={shopDomain}
          placeholder="mystore.myshopify.com"
          onChange={(e) => update(e.target.value)}
        />
        <p className="text-caption text-muted-foreground">
          Must end in <span className="font-mono">.myshopify.com</span>.
          Auto-populated post-OAuth in production.
        </p>
      </div>
    </div>
  );
}
