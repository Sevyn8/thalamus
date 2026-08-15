"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";

export default function SuperadminError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[superadmin/error.tsx]", error);
  }, [error]);

  const eventId =
    error instanceof ApiError && error.requestId
      ? error.requestId
      : error.digest ?? crypto.randomUUID();

  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-4 px-6 py-24 text-center">
      <h1 className="text-heading">Something went wrong.</h1>
      <p className="text-sm text-muted-foreground">
        The console hit an unexpected error. The event ID below helps support correlate it with logs.
      </p>
      <code className="rounded bg-muted px-2 py-1 text-xs">{eventId}</code>
      <Button onClick={() => reset()} className="mt-2">
        Try again
      </Button>
    </div>
  );
}
