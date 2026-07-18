"use client";

import { useId } from "react";

import { Input } from "@/components/ui/input";
import type { ConnectionConfig } from "@/types/dis";

type Props = {
  value: Partial<ConnectionConfig>;
  onChange: (next: Partial<ConnectionConfig>, valid: boolean) => void;
};

export function CsvScheduledForm({ value, onChange }: Props) {
  const v = value as Record<string, unknown>;
  const filePattern = (v.file_pattern as string | undefined) ?? "";
  const sourceUrl = (v.source_url_or_ftp as string | undefined) ?? "";
  const filePatternId = useId();
  const sourceUrlId = useId();

  function update(patch: Record<string, unknown>) {
    const merged: Partial<ConnectionConfig> = {
      type: "CSV_SCHEDULED",
      file_pattern: filePattern,
      source_url_or_ftp: sourceUrl,
      ...patch,
    };
    const fp = String(merged.file_pattern ?? "").trim();
    const url = String(merged.source_url_or_ftp ?? "").trim();
    const valid = fp.length > 0 && url.length > 0;
    onChange(merged, valid);
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <label htmlFor={filePatternId} className="text-label text-muted-foreground">
          File pattern
        </label>
        <Input
          id={filePatternId}
          type="text"
          value={filePattern}
          placeholder="sales_*.csv"
          onChange={(e) => update({ file_pattern: e.target.value })}
        />
      </div>
      <div className="flex flex-col gap-2">
        <label htmlFor={sourceUrlId} className="text-label text-muted-foreground">
          Source URL or FTP path
        </label>
        <Input
          id={sourceUrlId}
          type="text"
          value={sourceUrl}
          placeholder="https://exports.example.com/sales/ or ftp://host/path/"
          onChange={(e) => update({ source_url_or_ftp: e.target.value })}
        />
      </div>
    </div>
  );
}
