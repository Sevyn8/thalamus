"use client";

import { useId } from "react";

import { Input } from "@/components/ui/input";
import type { AuthType, ConnectionConfig } from "@/types/dis";

type Props = {
  value: Partial<ConnectionConfig>;
  onChange: (next: Partial<ConnectionConfig>, valid: boolean) => void;
};

export function PosApiGenericForm({ value, onChange }: Props) {
  const v = value as Record<string, unknown>;
  const endpoint = (v.endpoint_url as string | undefined) ?? "";
  const authType = (v.auth_type as AuthType | undefined) ?? "bearer";
  const credsRef = (v.credentials_ref as string | undefined) ?? "";
  const endpointId = useId();
  const authTypeId = useId();
  const credsRefId = useId();

  function update(patch: Record<string, unknown>) {
    const merged: Partial<ConnectionConfig> = {
      type: "POS_API_GENERIC",
      endpoint_url: endpoint,
      auth_type: authType,
      credentials_ref: credsRef,
      ...patch,
    };
    const e = (merged.endpoint_url as string | undefined) ?? "";
    const valid =
      e.trim().length > 0 &&
      /^https?:\/\//.test(e.trim()) &&
      String(merged.credentials_ref ?? "").trim().length > 0;
    onChange(merged, valid);
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
          placeholder="https://api.example.com/v1/transactions"
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
          placeholder="secret://tenant/connector-name"
          onChange={(e) => update({ credentials_ref: e.target.value })}
        />
        <p className="text-caption text-muted-foreground">
          Stored securely. Cloud Secret Manager integration in Phase 5d.
        </p>
      </div>
    </div>
  );
}
