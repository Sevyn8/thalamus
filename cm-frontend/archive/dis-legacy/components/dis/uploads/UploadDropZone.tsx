"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Upload as UploadIcon } from "lucide-react";

import { useCreateUpload } from "@/lib/dis/hooks/use-uploads";
import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";

// Always-visible drop-zone at the top of the uploads list. Modern
// pattern (Stripe, Vercel, Linear): one click to pick or drag-drop;
// no separate modal or wizard route. On success, route into
// /dis/uploads/[id] so the user lands on the mapping review surface
// (5c.1b) immediately after upload.
//
// 5c.1a scope: file is sent as metadata only (name, size). The blob
// itself isn't transmitted — see lib/dis/api/uploads.ts for the
// rationale and the multipart-migration flag.

export function UploadDropZone() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const mutation = useCreateUpload();

  function pick() {
    inputRef.current?.click();
  }

  async function submit(file: File) {
    setErrorMessage(null);
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setErrorMessage("Only .csv files are supported in v1.");
      return;
    }
    try {
      const created = await mutation.mutateAsync({ file });
      router.push(`/dis/uploads/${created.id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage("Upload failed. Try again.");
      }
    }
  }

  function onChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) void submit(file);
    e.target.value = "";
  }

  function onDrop(e: React.DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files[0];
    if (file) void submit(file);
  }

  const uploading = mutation.isPending;

  return (
    <div className="flex flex-col gap-2">
      <label
        htmlFor="dis-upload-drop-input"
        onDragOver={(e) => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={onDrop}
        onClick={(e) => {
          // base label-for already triggers the input; preventing double-fire
          // when the user clicks anywhere on the styled label.
          if ((e.target as HTMLElement).tagName === "INPUT") return;
          e.preventDefault();
          if (!uploading) pick();
        }}
        className={cn(
          "flex cursor-pointer items-center justify-center gap-3 rounded-md border border-dashed border-border bg-card/30 px-6 py-8 text-sm transition-colors duration-150 ease-out",
          dragActive && "border-border-strong bg-surface-raised",
          !dragActive && "hover:bg-surface-raised hover:border-border-strong",
          uploading && "pointer-events-none opacity-70",
        )}
      >
        {uploading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            <span className="text-muted-foreground">Uploading…</span>
          </>
        ) : (
          <>
            <UploadIcon className="h-4 w-4 text-muted-foreground" />
            <span>
              <span className="text-foreground">Drop a CSV here</span>{" "}
              <span className="text-muted-foreground">or click to choose a file</span>
            </span>
          </>
        )}
        <input
          id="dis-upload-drop-input"
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          onChange={onChange}
          className="sr-only"
          disabled={uploading}
        />
      </label>
      {errorMessage ? (
        <p className="text-sm text-danger" role="alert">
          {errorMessage}
        </p>
      ) : null}
    </div>
  );
}
