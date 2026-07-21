import { NextResponse } from "next/server";

// Runtime config bridge for the client. Non-NEXT_PUBLIC_ env vars are
// server-only and read here at request time, so the API base URL and auth
// mode can change per deployment (a revision bounce) without a rebuild.
//
// force-dynamic is load-bearing: without it Next.js could prerender this
// GET at build time and freeze the env values into the static response,
// which is the exact build-time coupling this route exists to remove.
export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({
    apiBaseUrl: process.env.API_BASE_URL ?? "",
  });
}
