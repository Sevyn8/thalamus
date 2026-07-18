"use client";

import type { TemplateDomain, TemplateVisibility } from "@/types/dis";

// Phase 5e.6 step 3: review the selected domains + meta + a preview
// of the merged column structure. Column preview pulls field names
// from the canonical-schema list passed in (avoids fetching here).

type DomainPreview = {
  domain: TemplateDomain;
  fieldIds: string[];
};

type Props = {
  name: string;
  description: string;
  visibility: TemplateVisibility;
  domainPreviews: DomainPreview[];
};

const DOMAIN_LABEL: Record<TemplateDomain, string> = {
  sales: "Sales",
  inventory: "Inventory",
  customers: "Customers",
  suppliers: "Suppliers",
  stores: "Stores",
  products: "Products",
};

export function StepTemplateReview({
  name,
  description,
  visibility,
  domainPreviews,
}: Props) {
  const totalColumns = domainPreviews.reduce(
    (acc, dp) => acc + dp.fieldIds.length,
    0,
  );
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <span className="text-label text-muted-foreground">Review</span>
        <div className="grid grid-cols-1 gap-3 rounded-md border border-border bg-card/30 p-4 sm:grid-cols-2">
          <ReviewItem label="Name" value={name || "—"} />
          <ReviewItem
            label="Visibility"
            value={visibility === "TENANT_SHARED" ? "Tenant-shared" : "Private"}
          />
          <ReviewItem
            label="Domains"
            value={domainPreviews.map((d) => DOMAIN_LABEL[d.domain]).join(" · ")}
          />
          <ReviewItem
            label="Total columns"
            value={String(totalColumns)}
          />
        </div>
        {description ? (
          <p className="text-caption text-muted-foreground">{description}</p>
        ) : null}
      </div>

      <div className="flex flex-col gap-3">
        <span className="text-label text-muted-foreground">Column preview</span>
        <p className="text-caption text-muted-foreground">
          Columns appear in the merged CSV in the order shown — schema-grouped
          per the order you picked. Field names are domain-prefixed where
          needed to avoid duplicate columns (3 of the v1 domains share a
          few field names).
        </p>
        <div className="flex flex-col gap-3">
          {domainPreviews.map((dp) => (
            <div
              key={dp.domain}
              className="flex flex-col gap-2 rounded-md border border-border bg-card/30 p-3"
            >
              <span className="text-body-strong">
                {DOMAIN_LABEL[dp.domain]}{" "}
                <span className="text-caption text-muted-foreground">
                  ({dp.fieldIds.length} columns)
                </span>
              </span>
              <div className="flex flex-wrap gap-1.5">
                {dp.fieldIds.map((fid) => (
                  <code
                    key={fid}
                    className="rounded-sm bg-muted px-1.5 py-0.5 font-mono text-xs"
                  >
                    {fid}
                  </code>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ReviewItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-label text-muted-foreground">{label}</span>
      <span className="text-sm">{value}</span>
    </div>
  );
}
