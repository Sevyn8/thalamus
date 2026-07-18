import { ApiError } from "@/lib/api/client";
import type { ApiErrorBody } from "@/lib/api/types";
import { getAuthToken } from "@/lib/auth/getAuthToken";

// Mirror of lib/api/client.ts pointed at the DIS backend. ApiError is
// reused (not duplicated) because the {code, message, details,
// request_id} envelope is Sanjeev's framework-level contract, not an
// Ithina-specific shape — one class lets `instanceof ApiError` work
// uniformly across both clients. disApiFetch and disQs are renamed
// duplicates so each product has its own base URL surface; they can
// diverge later without affecting Ithina's call sites.
//
// Idempotency-Key is NOT added here — same as lib/api/client.ts. The
// Ithina pattern generates the key per-call inside resource modules
// (see lib/api/tenants.ts), so a 500-retry produces two distinct
// intents. DIS resource modules will follow the same pattern when
// mutation surfaces arrive (Phase 5c.1+).

const DIS_API_BASE_URL = process.env.NEXT_PUBLIC_DIS_API_BASE_URL ?? "";

function joinUrl(base: string, path: string): string {
  if (!base) return path;
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return `${base.replace(/\/+$/, "")}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function disApiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = joinUrl(DIS_API_BASE_URL, path);
  const token = getAuthToken();

  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(url, { ...init, headers, credentials: "omit" });
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

export function disQs(params: Record<string, unknown> | undefined): string {
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
