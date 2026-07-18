"use client";

import { useId } from "react";

import { Input } from "@/components/ui/input";
import type { ConnectionConfig } from "@/types/dis";

type Props = {
  value: Partial<ConnectionConfig>;
  onChange: (next: Partial<ConnectionConfig>, valid: boolean) => void;
};

export function FtpForm({ value, onChange }: Props) {
  const v = value as Record<string, unknown>;
  const host = (v.host as string | undefined) ?? "";
  const port = (v.port as number | undefined) ?? 21;
  const path = (v.path as string | undefined) ?? "";
  const username = (v.username as string | undefined) ?? "";
  const credsRef = (v.credentials_ref as string | undefined) ?? "";
  const hostId = useId();
  const portId = useId();
  const pathId = useId();
  const usernameId = useId();
  const credsRefId = useId();

  function update(patch: Record<string, unknown>) {
    const merged: Partial<ConnectionConfig> = {
      type: "FTP",
      host,
      port,
      path,
      username,
      credentials_ref: credsRef,
      ...patch,
    };
    const valid =
      String(merged.host ?? "").trim().length > 0 &&
      typeof merged.port === "number" &&
      String(merged.path ?? "").trim().length > 0 &&
      String(merged.username ?? "").trim().length > 0 &&
      String(merged.credentials_ref ?? "").trim().length > 0;
    onChange(merged, valid);
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="flex flex-col gap-2 sm:col-span-2">
          <label htmlFor={hostId} className="text-label text-muted-foreground">
            Host
          </label>
          <Input
            id={hostId}
            type="text"
            value={host}
            placeholder="ftp.example.com"
            onChange={(e) => update({ host: e.target.value })}
          />
        </div>
        <div className="flex flex-col gap-2">
          <label htmlFor={portId} className="text-label text-muted-foreground">
            Port
          </label>
          <Input
            id={portId}
            type="number"
            value={port}
            min={1}
            max={65535}
            onChange={(e) => update({ port: Number(e.target.value) || 21 })}
          />
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <label htmlFor={pathId} className="text-label text-muted-foreground">
          Path
        </label>
        <Input
          id={pathId}
          type="text"
          value={path}
          placeholder="/exports/inventory/"
          onChange={(e) => update({ path: e.target.value })}
        />
      </div>
      <div className="flex flex-col gap-2">
        <label htmlFor={usernameId} className="text-label text-muted-foreground">
          Username
        </label>
        <Input
          id={usernameId}
          type="text"
          value={username}
          placeholder="dis-pull"
          onChange={(e) => update({ username: e.target.value })}
        />
      </div>
      <div className="flex flex-col gap-2">
        <label htmlFor={credsRefId} className="text-label text-muted-foreground">
          Credentials reference
        </label>
        <Input
          id={credsRefId}
          type="text"
          value={credsRef}
          placeholder="secret://tenant/ftp-credentials"
          onChange={(e) => update({ credentials_ref: e.target.value })}
        />
        <p className="text-caption text-muted-foreground">
          Stored securely. Cloud Secret Manager integration in Phase 5d.
        </p>
      </div>
    </div>
  );
}
