// Direct browser upload to a GCS V4 signed PUT URL (Slice 4). Uses
// XMLHttpRequest (not fetch) because we need upload progress events, and
// AbortSignal support so the caller can cancel. This does NOT go through
// apiFetch: the signed URL is a full GCS URL and must NOT carry our
// backend Authorization header; the signature IS the authorization.
//
// The Content-Type sent here MUST match the content_type the backend
// signed the URL with, or GCS rejects the PUT with a signature mismatch.

export class UploadError extends Error {
  readonly status: number;
  readonly aborted: boolean;

  constructor(message: string, opts: { status?: number; aborted?: boolean }) {
    super(message);
    this.name = "UploadError";
    this.status = opts.status ?? 0;
    this.aborted = opts.aborted ?? false;
  }
}

export function uploadToSignedUrl(args: {
  url: string;
  file: File;
  contentType: string;
  onProgress?: (percent: number) => void;
  signal?: AbortSignal;
}): Promise<void> {
  const { url, file, contentType, onProgress, signal } = args;

  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new UploadError("Upload cancelled", { aborted: true }));
      return;
    }

    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url, true);
    xhr.setRequestHeader("Content-Type", contentType);

    const onAbort = () => xhr.abort();
    signal?.addEventListener("abort", onAbort, { once: true });

    const cleanup = () => signal?.removeEventListener("abort", onAbort);

    xhr.upload.onprogress = (e) => {
      if (onProgress && e.lengthComputable) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };

    xhr.onload = () => {
      cleanup();
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(
          new UploadError(
            `Upload failed (HTTP ${xhr.status})`,
            { status: xhr.status },
          ),
        );
      }
    };

    xhr.onerror = () => {
      cleanup();
      reject(new UploadError("Upload failed (network error)", {}));
    };

    xhr.onabort = () => {
      cleanup();
      reject(new UploadError("Upload cancelled", { aborted: true }));
    };

    xhr.send(file);
  });
}
