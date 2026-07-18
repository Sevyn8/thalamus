"use client";

import { useId } from "react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { AuthType, ConnectionConfig } from "@/types/dis";

type Props = {
  value: Partial<ConnectionConfig>;
  onChange: (next: Partial<ConnectionConfig>, valid: boolean) => void;
};

// Headers UI: JSON textarea. v1 doesn't pretty-print or validate keys
// individually; just parse on blur and surface a parse error inline.
// Real backend likely accepts headers as a structured object; v1
// renders them as JSON for compactness with the catch-all REST shape.
export function RestApiGenericForm({ value, onChange }: Props) {
  const v = value as Record<string, unknown>;
  const endpoint = (v.endpoint_url as string | undefined) ?? "";
  const authType = (v.auth_type as AuthType | undefined) ?? "bearer";
  const credsRef = (v.credentials_ref as string | undefined) ?? "";
  const headers = (v.headers as Record<string, string> | undefined) ?? {};
  const headersText = JSON.stringify(headers, null, 2);
  const endpointId = useId();
  const authTypeId = useId();
  const credsRefId = useId();
  const headersId = useId();

  function update(patch: Record<string, unknown>) {
    const merged: Partial<ConnectionConfig> = {
      type: "REST_API_GENERIC",
      endpoint_url: endpoint,
      auth_type: authType,
      credentials_ref: credsRef,
      headers,
      ...patch,
    };
    const e = String(merged.endpoint_url ?? "").trim();
    const valid =
      e.length > 0 &&
      /^https?:\/\//.test(e) &&
      String(merged.credentials_ref ?? "").trim().length > 0;
    onChange(merged, valid);
  }

  function onHeadersText(text: string) {
    if (text.trim() === "") {
      update({ headers: {} });
      return;
    }
    try {
      const parsed = JSON.parse(text) as Record<string, string>;
      update({ headers: parsed });
    } catch {
      // Invalid JSON: keep existing headers; do not patch. The user
      // can keep typing until the JSON is valid. valid stays computed
      // off the URL + credsRef so headers parse error doesn't block
      // Next on its own (real backend can reject malformed headers
      // at test-connection).
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <label htmlFor={endpointId} className="text-label text-muted-foreground">
          Endpoint URL
        </label>
        <Input
          id={endpointId}
          type="text"
          value={endpoint}
          placeholder="https://api.example.com/v2/data"
          onChange={(e) => update({ endpoint_url: e.target.value })}
        />
      </div>
      <div className="flex flex-col gap-2">
        <label htmlFor={authTypeId} className="text-label text-muted-foreground">
          Auth type
        </label>
        <select
          id={authTypeId}
          value={authType}
          onChange={(e) => update({ auth_type: e.target.value as AuthType })}
          className="h-9 rounded-md border border-input bg-background px-2.5 py-1 text-sm focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none dark:bg-input/30"
        >
          <option value="basic">Basic</option>
          <option value="bearer">Bearer</option>
          <option value="api_key">API key</option>
        </select>
      </div>
      <div className="flex flex-col gap-2">
        <label htmlFor={credsRefId} className="text-label text-muted-foreground">
          Credentials reference
        </label>
        <Input
          id={credsRefId}
          type="text"
          value={credsRef}
          placeholder="secret://tenant/api-credentials"
          onChange={(e) => update({ credentials_ref: e.target.value })}
        />
      </div>
      <div className="flex flex-col gap-2">
        <label htmlFor={headersId} className="text-label text-muted-foreground">
          Custom headers (JSON)
        </label>
        <textarea
          id={headersId}
          defaultValue={headersText}
          placeholder='{"X-Tenant-Id": "tenant-prod"}'
          rows={4}
          onBlur={(e) => onHeadersText(e.target.value)}
          className={cn(
            "rounded-md border border-input bg-background px-2.5 py-1.5 text-sm font-mono",
            "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
            "dark:bg-input/30",
          )}
        />
      </div>
    </div>
  );
}
