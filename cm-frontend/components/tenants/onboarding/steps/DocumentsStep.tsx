"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { AlertCircle, Check, Download, Loader2, Trash2, UploadCloud, X, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Chip, type Tone } from "@/components/shared/Chips";
import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { EmptyState } from "@/components/shared/EmptyState";
import { ApiError } from "@/lib/api/client";
import { documentsApi } from "@/lib/api/documents";
import { uploadToSignedUrl, UploadError } from "@/lib/api/upload";
import { useOnboardingLookups } from "@/lib/hooks/use-onboarding-lookups";
import {
  useDeleteDocument,
  useDocuments,
  useDocumentsInvalidate,
  useRejectDocument,
  useVerifyDocument,
} from "@/lib/hooks/use-documents";
import type { DocumentRead } from "@/types/api";
import { Input } from "@/components/ui/input";
import {
  FieldLabel,
  SELECT_CLASS,
} from "@/components/tenants/onboarding/fields";
import { StepShell } from "@/components/tenants/onboarding/StepShell";
import type { StepProps } from "@/components/tenants/onboarding/step-props";

const ALLOWED_CONTENT_TYPES = ["application/pdf", "image/png", "image/jpeg"] as const;
const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;

const STATUS_TONE: Record<string, Tone> = {
  PENDING_REVIEW: "amber",
  VERIFIED: "green",
  REJECTED: "red",
};
const STATUS_LABEL: Record<string, string> = {
  PENDING_REVIEW: "Pending review",
  VERIFIED: "Verified",
  REJECTED: "Rejected",
};

function formatBytes(n: number | null): string {
  if (n === null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function DocumentsStep({ tenantId, onSaved, onBack, setDirty, mode }: StepProps) {
  const lookups = useOnboardingLookups();
  const docTypes = lookups.data?.document_type ?? [];
  const typeLabel = (code: string) =>
    docTypes.find((d) => d.code === code)?.display_name ?? code;

  const query = useDocuments(tenantId);
  const del = useDeleteDocument(tenantId);
  const verify = useVerifyDocument(tenantId);
  const reject = useRejectDocument(tenantId);
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const invalidate = useDocumentsInvalidate();

  const [storageUnavailable, setStorageUnavailable] = useState(false);
  const [documentType, setDocumentType] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [inlineError, setInlineError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Documents step commits each action immediately; there is no unsaved
  // form state, so navigation away is always safe.
  useEffect(() => setDirty(false), [setDirty]);

  function resetUploader() {
    setFile(null);
    setDocumentType("");
    setProgress(0);
    setInlineError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function onUpload() {
    setInlineError(null);
    if (!documentType) {
      setInlineError("Choose a document type.");
      return;
    }
    if (!file) {
      setInlineError("Choose a file to upload.");
      return;
    }
    if (!(ALLOWED_CONTENT_TYPES as readonly string[]).includes(file.type)) {
      setInlineError("Allowed types: PDF, PNG, JPEG.");
      return;
    }
    if (file.size > MAX_FILE_SIZE_BYTES) {
      setInlineError("File exceeds the 10 MB limit.");
      return;
    }

    setUploading(true);
    setProgress(0);

    // Step 1 of the upload: reserve the row + get the signed PUT URL.
    let created;
    try {
      created = await documentsApi.createUploadUrl(tenantId, {
        document_type: documentType,
        file_name: file.name,
        content_type: file.type,
        file_size_bytes: file.size,
      });
    } catch (err) {
      setUploading(false);
      if (err instanceof ApiError) {
        if (err.code === "DOCUMENT_STORAGE_UNAVAILABLE") {
          setStorageUnavailable(true);
          return;
        }
        // INVALID_CONTENT_TYPE / FILE_TOO_LARGE / INVALID_LOOKUP_CODE, etc.
        setInlineError(err.message);
        return;
      }
      toast.error("Could not start the upload. Please try again.");
      return;
    }

    // The row now exists in PENDING_REVIEW. Show it in the list immediately.
    invalidate();

    // Step 2 of the upload: direct PUT to GCS. On any failure/cancel, delete the row we
    // just created so no orphan PENDING_REVIEW row pollutes the counts.
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await uploadToSignedUrl({
        url: created.upload_url,
        file,
        contentType: file.type,
        onProgress: setProgress,
        signal: controller.signal,
      });
      toast.success("Document uploaded");
      invalidate();
      resetUploader();
    } catch (err) {
      await cleanupFailedUpload(created.document, err);
    } finally {
      setUploading(false);
      abortRef.current = null;
    }
  }

  async function cleanupFailedUpload(doc: DocumentRead, err: unknown) {
    const cancelled = err instanceof UploadError && err.aborted;
    try {
      await documentsApi.remove(tenantId, doc.id);
      invalidate();
      if (cancelled) {
        toast.message("Upload cancelled");
      } else {
        toast.error("Upload failed. You can try again.");
      }
      // Keep the chosen type/file so the operator can retry immediately.
    } catch {
      // Cleanup DELETE itself failed: surface the orphan row (with its
      // manual-delete affordance) rather than hiding it.
      invalidate();
      toast.error(
        "Upload failed and the draft row could not be removed automatically. Delete it manually below.",
      );
    }
  }

  function onCancelUpload() {
    abortRef.current?.abort();
  }

  async function onDownload(doc: DocumentRead) {
    try {
      const res = await documentsApi.getDownloadUrl(tenantId, doc.id);
      window.open(res.download_url, "_blank", "noopener,noreferrer");
    } catch (err) {
      if (err instanceof ApiError && err.code === "DOCUMENT_STORAGE_UNAVAILABLE") {
        setStorageUnavailable(true);
        return;
      }
      toast.error("Could not open the document. Please try again.");
    }
  }

  async function onDelete(doc: DocumentRead) {
    try {
      await del.mutateAsync(doc.id);
      toast.success("Document deleted");
    } catch (err) {
      if (err instanceof ApiError) {
        toast.error(err.message);
        return;
      }
      toast.error("Could not delete the document. Please try again.");
    }
  }

  async function onVerify(doc: DocumentRead) {
    try {
      await verify.mutateAsync(doc.id);
      toast.success("Document verified");
    } catch (err) {
      if (err instanceof ApiError) {
        toast.error(err.message);
        return;
      }
      toast.error("Could not verify the document. Please try again.");
    }
  }

  function startReject(doc: DocumentRead) {
    setRejectingId(doc.id);
    setRejectReason("");
  }

  function cancelReject() {
    setRejectingId(null);
    setRejectReason("");
  }

  async function onReject(doc: DocumentRead) {
    if (!rejectReason.trim()) return;
    try {
      await reject.mutateAsync({
        documentId: doc.id,
        body: { rejection_reason: rejectReason.trim() },
      });
      toast.success("Document rejected");
      cancelReject();
    } catch (err) {
      if (err instanceof ApiError) {
        toast.error(err.message);
        return;
      }
      toast.error("Could not reject the document. Please try again.");
    }
  }

  const items = query.data?.items ?? [];

  return (
    <StepShell
      title="Documents"
      description="Upload the client's onboarding documents. Verification is handled by staff outside this wizard."
      footer={
        // Upload / verify / reject / delete all persist immediately, so
        // edit mode has nothing to advance to: drop the footer. Onboarding
        // keeps Save & continue.
        mode === "edit" ? undefined : (
          <div className="flex items-center justify-between border-t border-border px-6 py-4">
            <div>
              {onBack ? (
                <Button type="button" variant="outline" onClick={onBack}>Back</Button>
              ) : null}
            </div>
            <Button type="button" onClick={onSaved}>Save & continue</Button>
          </div>
        )
      }
    >
      <div className="flex flex-col gap-6">
        {storageUnavailable ? (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-[var(--warning-line)] bg-[var(--warning-bg)] p-3 text-sm dark:bg-warning/5"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <div>
              <p className="font-medium">Document storage is not configured.</p>
              <p className="text-muted-foreground">
                Uploads and downloads are unavailable in this environment. Existing
                document records are still listed below.
              </p>
            </div>
          </div>
        ) : null}

        {/* Uploader */}
        <div className="flex flex-col gap-3 rounded-md border border-border p-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <FieldLabel htmlFor="doc-type">Document type</FieldLabel>
              <select
                id="doc-type"
                className={SELECT_CLASS}
                value={documentType}
                disabled={uploading}
                onChange={(e) => setDocumentType(e.target.value)}
              >
                <option value="">Select...</option>
                {docTypes.map((d) => (
                  <option key={d.code} value={d.code}>{d.display_name}</option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <FieldLabel htmlFor="doc-file">File (PDF, PNG, JPEG; max 10 MB)</FieldLabel>
              <input
                ref={fileInputRef}
                id="doc-file"
                type="file"
                accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
                disabled={uploading}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="text-sm file:mr-3 file:rounded-md file:border file:border-input file:bg-background file:px-2.5 file:py-1 file:text-sm"
              />
            </div>
          </div>

          {inlineError ? (
            <p className="text-xs text-danger">{inlineError}</p>
          ) : null}

          {uploading ? (
            <div className="flex items-center gap-3">
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full bg-primary transition-all"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <span className="w-10 text-right text-xs tabular-nums text-muted-foreground">
                {progress}%
              </span>
              <Button type="button" variant="ghost" size="icon-sm" aria-label="Cancel upload" onClick={onCancelUpload}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            <div>
              <Button type="button" onClick={onUpload} disabled={storageUnavailable}>
                <UploadCloud className="mr-1.5 h-4 w-4" /> Upload document
              </Button>
            </div>
          )}
        </div>

        {/* List */}
        {query.isLoading ? (
          <Skeleton variant="card" />
        ) : query.error ? (
          <ErrorInline message="Could not load documents." onRetry={() => query.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState title="No documents yet" body="Upload the client's onboarding documents above." />
        ) : (
          <ul className="flex flex-col divide-y divide-border rounded-md border border-border">
            {items.map((doc) => (
              <li key={doc.id} className="flex flex-col gap-2 px-4 py-3">
              <div className="flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium">
                      {doc.file_name ?? "(unnamed)"}
                    </span>
                    <Chip tone={STATUS_TONE[doc.verification_status] ?? "grey"}>
                      {STATUS_LABEL[doc.verification_status] ?? doc.verification_status}
                    </Chip>
                  </div>
                  <p className="truncate text-xs text-muted-foreground">
                    {typeLabel(doc.document_type)}
                    {doc.file_size_bytes !== null ? ` · ${formatBytes(doc.file_size_bytes)}` : ""}
                  </p>
                  {doc.verification_status === "REJECTED" && doc.rejection_reason ? (
                    <p className="mt-0.5 text-xs text-danger">
                      Rejected: {doc.rejection_reason}
                    </p>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button type="button" variant="ghost" size="icon-sm" aria-label={`Download ${doc.file_name ?? "document"}`} onClick={() => onDownload(doc)}>
                    <Download className="h-4 w-4" />
                  </Button>
                  {doc.verification_status === "PENDING_REVIEW" ? (
                    <>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Verify ${doc.file_name ?? "document"}`}
                        disabled={verify.isPending}
                        onClick={() => onVerify(doc)}
                      >
                        {verify.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4 text-success" />}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Reject ${doc.file_name ?? "document"}`}
                        onClick={() => startReject(doc)}
                      >
                        <XCircle className="h-4 w-4 text-danger" />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Delete ${doc.file_name ?? "document"}`}
                        disabled={del.isPending}
                        onClick={() => onDelete(doc)}
                      >
                        {del.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                      </Button>
                    </>
                  ) : null}
                </div>
              </div>
              {rejectingId === doc.id ? (
                <div className="flex items-end gap-2 rounded-md bg-muted/30 p-2">
                  <div className="flex flex-1 flex-col gap-1">
                    <FieldLabel htmlFor={`reject-${doc.id}`}>
                      Rejection reason
                    </FieldLabel>
                    <Input
                      id={`reject-${doc.id}`}
                      value={rejectReason}
                      onChange={(e) => setRejectReason(e.target.value)}
                      placeholder="Why is this document rejected?"
                    />
                  </div>
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    disabled={reject.isPending || !rejectReason.trim()}
                    onClick={() => onReject(doc)}
                  >
                    {reject.isPending ? (
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    ) : null}
                    Reject
                  </Button>
                  <Button type="button" variant="outline" size="sm" onClick={cancelReject}>
                    Cancel
                  </Button>
                </div>
              ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </StepShell>
  );
}
