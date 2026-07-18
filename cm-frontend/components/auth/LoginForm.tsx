"use client";

import { useId, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { loginWithEmailPassword } from "@/lib/auth/login";

// Phase 5d.7: production-side login form. Replaces the disabled
// "Continue with Auth0" button from 5d.1's scaffolding. Form is
// real (POSTs to /api/v1/auth/login); backend endpoint isn't
// shipped yet, so non-2xx responses surface a friendly
// "service unavailable" message that points to the dev-login
// grid below.
//
// HTML5 native validation only (type="email" + required) — no Zod
// schema for v1. Server is the ultimate arbiter; client-side
// validation overkill for a form that's pre-shipment of the
// backend contract.
//
// No forgot-password link in v1 — out of scope per 5d.7 spec.
// When Auth0 lands, the form becomes the load-bearing production
// path; persona grid degrades to dev-only at that point.

export function LoginForm() {
  const router = useRouter();
  const emailId = useId();
  const passwordId = useId();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPending(true);
    setError(null);
    const result = await loginWithEmailPassword({ email, password });
    if (result.ok) {
      toast.success("Signed in");
      router.replace("/my-ithina");
      return;
    }
    setError(result.message);
    setPending(false);
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <label
          htmlFor={emailId}
          className="text-label text-muted-foreground"
        >
          Email
        </label>
        <Input
          id={emailId}
          name="email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={pending}
          placeholder="you@company.com"
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <label
          htmlFor={passwordId}
          className="text-label text-muted-foreground"
        >
          Password
        </label>
        <Input
          id={passwordId}
          name="password"
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={pending}
        />
      </div>
      {error ? <ErrorInline message={error} /> : null}
      <div className="mt-1">
        <Button type="submit" disabled={pending}>
          {pending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Signing in…
            </>
          ) : (
            "Sign in"
          )}
        </Button>
      </div>
    </form>
  );
}
