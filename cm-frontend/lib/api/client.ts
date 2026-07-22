import type { ApiErrorBody } from "./types";
import { ensureAuthToken } from "@/lib/auth/getAuthToken";
import { ensureRuntimeConfig, getApiBaseUrl } from "@/lib/config/runtime-config";

export class ApiError extends Error {
  readonly code: string;
  readonly details: unknown;
  readonly requestId: string;
  readonly status: number;

  constructor(args: {
    code: string;
    message: string;
    details: unknown;
    requestId: string;
    status: number;
  }) {
    super(args.message);
    this.name = "ApiError";
    this.code = args.code;
    this.details = args.details;
    this.requestId = args.requestId;
    this.status = args.status;
  }
}

// Real backend is the only mode. The base URL is REQUIRED and read at
// runtime from the runtime-config store (server env API_BASE_URL, bridged
// to the client via /api/config). It is no longer inlined at build time,
// so the same image can be promoted across projects. apiFetch awaits
// ensureRuntimeConfig() before resolving, so the URL is always populated
// before the first call; an empty value still throws.
function joinUrl(base: string, path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return `${base.replace(/\/+$/, "")}${path.startsWith("/") ? path : `/${path}`}`;
}

function resolveUrl(path: string): string {
  const base = getApiBaseUrl();
  if (!base) {
    throw new Error(
      "API base URL is not configured. Set the non-prefixed API_BASE_URL server env; the client reads it from /api/config at runtime.",
    );
  }
  return joinUrl(base, path);
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  // Ensure the runtime config (API base URL) is loaded before the first
  // request. Deduped + cached, so this is a no-op after the first call.
  // Keeps apiFetch's signature unchanged while removing the build-time
  // base-URL coupling.
  await ensureRuntimeConfig();

  const fetchInit = init ?? {};
  const url = resolveUrl(path);
  // Guarantee the session token is fetched+cached before the request fires
  // (same dedupe/cache discipline as ensureRuntimeConfig above). For an
  // authenticated session the token is now populated before the header is set,
  // closing the early-load window that sent headerless requests -> 401. No
  // session resolves to null and the Authorization header is simply omitted.
  const token = await ensureAuthToken();

  const headers = new Headers(fetchInit.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (fetchInit.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(url, { ...fetchInit, headers, credentials: "omit" });
  const requestId = response.headers.get("x-request-id") ?? "";

  if (!response.ok) {
    let body: Partial<ApiErrorBody> = {};
    try {
      body = (await response.json()) as Partial<ApiErrorBody>;
    } catch {
      // empty / non-JSON error body
    }
    throw new ApiError({
      code: body.code ?? `HTTP_${response.status}`,
      message: body.message ?? response.statusText,
      details: body.details ?? null,
      requestId: body.request_id ?? requestId,
      status: response.status,
    });
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function qs(params: Record<string, unknown> | undefined): string {
  if (!params) return "";
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      if (value.length > 0) usp.set(key, value.join(","));
    } else {
      usp.set(key, String(value));
    }
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}
