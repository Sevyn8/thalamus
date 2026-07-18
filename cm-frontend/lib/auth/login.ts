// Phase 5d.7: pre-Auth0 login dispatch. Standalone from lib/api/
// client.ts because the form submits BEFORE any JWT exists —
// apiFetch attaches Authorization headers from getAuthToken() and
// would mis-signal to the backend on the login request. Fetch
// directly here.
//
// Contract: POST /api/v1/auth/login with { email, password }. The
// deployed backend's auth middleware currently 401s on this path
// (endpoint not shipped); when Auth0 / native login lands in
// Phase 5e+, this module's response shape becomes load-bearing.
//
// Error normalization: any non-2xx folds into a single friendly
// "service unavailable" outcome at the form level — distinguishing
// 401 (auth-middleware short-circuit) from 404 (no endpoint) from
// 5xx (server error) doesn't help the user, and the 401-pre-shipment
// case is misleading by itself.

import { ensureRuntimeConfig, getApiBaseUrl } from "@/lib/config/runtime-config";

export type LoginInput = {
  email: string;
  password: string;
};

export type LoginResult =
  | { ok: true; token: string }
  | {
      ok: false;
      status: number;
      // Friendly message ready for direct render. Backend's raw
      // {code, message} envelope is mapped to this here.
      message: string;
    };

export async function loginWithEmailPassword(
  input: LoginInput,
): Promise<LoginResult> {
  await ensureRuntimeConfig();
  const base = getApiBaseUrl();
  const url = base
    ? `${base.replace(/\/+$/, "")}/api/v1/auth/login`
    : "/api/v1/auth/login";
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
      credentials: "omit",
    });
    if (!response.ok) {
      return {
        ok: false,
        status: response.status,
        message:
          "Sign-in service is unavailable. Use the dev login below to continue.",
      };
    }
    const body = (await response.json()) as { token?: string };
    if (typeof body.token !== "string") {
      return {
        ok: false,
        status: response.status,
        message:
          "Sign-in service returned an unexpected response. Use the dev login below to continue.",
      };
    }
    return { ok: true, token: body.token };
  } catch {
    return {
      ok: false,
      status: 0,
      message:
        "Sign-in service is unavailable. Use the dev login below to continue.",
    };
  }
}
