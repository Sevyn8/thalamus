# Prompt — Step 1.1: Scaffold Next.js + dependencies

> Paste this after `00-bootstrap.md` has been run. This is the first build step in a fresh repo.

---

## Pre-flight

Before doing any work, verify:

```bash
pwd                              # /home/neerj/projects/admin-frontend
node --version                   # v18+ (v20+ preferred)
pnpm --version                   # any recent version
ls -la                           # confirm what's already here
git status                       # confirm clean or note pending changes
```

If `package.json` already exists and is non-empty, STOP and tell the user. Either Step 1.1 has already run (check `BUILD_PLAN.md` for status) or there is unexpected state to investigate.

---

## Step ID and intent

**Step 1.1** — Scaffold Next.js with the locked stack and configuration.

This is a CLAUDE_CODE step. A running Next.js dev server with the full stack installed and configured. Dark theme as default. TypeScript strict. No business logic yet.

---

## Scope in

### Scaffold

Create the Next.js app in the current directory:

```bash
pnpm create next-app@latest . \
  --typescript \
  --tailwind \
  --eslint \
  --app \
  --src-dir false \
  --import-alias "@/*" \
  --use-pnpm
```

If the prompt asks any question the flags don't cover, answer with the modern default. Confirm with the user before answering anything that feels load-bearing (e.g., turbopack vs webpack — pick stable default unless the user says otherwise).

### Dependencies to add

After scaffold, install:

```bash
pnpm add @tanstack/react-query
pnpm add msw
pnpm add react-hook-form zod @hookform/resolvers
pnpm add @auth0/nextjs-auth0
pnpm add jose                # for stub JWT minting in dev
pnpm add lucide-react        # icons used throughout the prototype
pnpm add sonner              # toasts
pnpm add date-fns            # timestamps
pnpm add clsx tailwind-merge # for shadcn cn() helper
```

Dev dependencies:

```bash
pnpm add -D @types/node
pnpm add -D msw@latest
```

### shadcn/ui setup

Initialise shadcn:

```bash
pnpm dlx shadcn@latest init
```

Answer prompts:
- Style: Default
- Base colour: Slate (we'll customise palette later)
- CSS variables: Yes
- Components alias: `@/components`
- Utils alias: `@/lib/utils`

Install the primitives we know we'll need (do all at once):

```bash
pnpm dlx shadcn@latest add button card badge input dropdown-menu dialog sheet tabs table toast skeleton tooltip avatar separator scroll-area
```

### TypeScript strict

Edit `tsconfig.json` to ensure strict mode is on. The Next.js scaffold uses strict by default, but verify these are present in `compilerOptions`:

```json
"strict": true,
"noUncheckedIndexedAccess": true,
"noImplicitOverride": true
```

### Tailwind config

The scaffold creates `tailwind.config.ts`. Confirm it exists and includes the shadcn paths. Don't customise the palette in this step — that is part of Step 1.4 (chrome) when the prototype's colours go in.

### Dark theme as default

In `app/layout.tsx`, add `className="dark"` to the `<html>` tag. Verify the dark colour scheme renders by running `pnpm dev` and visiting the page.

### Environment variables

Create `.env.example` and `.env.local`:

```bash
# .env.example
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_AUTH_MODE=stub
NEXT_PUBLIC_REGION=US
NEXT_PUBLIC_DEMO_MODE=false

# Auth0 (used when AUTH_MODE=auth0; leave blank in stub mode)
NEXT_PUBLIC_AUTH0_DOMAIN=
NEXT_PUBLIC_AUTH0_CLIENT_ID=
AUTH0_CLIENT_SECRET=
AUTH0_SECRET=
```

Copy `.env.example` to `.env.local` for local dev.

Add `.env.local` to `.gitignore` (it should already be there from the Next.js scaffold; verify).

### Quick smoke

Run `pnpm dev` and visit `http://localhost:3000`. Confirm the default Next.js page renders in dark mode without console errors.

Run `pnpm tsc --noEmit` to confirm TypeScript compiles cleanly.

### Repository documentation

Two repo-level documents land in this commit alongside the scaffold. Both have been pre-drafted by the user and should be present in the repo root before this step is run; if they are not, STOP and ask the user to drop them in before proceeding.

- `README.md` — locked decisions, stack, API contract, auth strategy, mock-first data plane, repo layout, environment variables. The orientation document for anyone (including future Claude Code sessions) entering the repo.
- `BUILD_PLAN.md` — step checklist with status legend, foundation-first order, what gets cut if the day runs long.

After scaffolding, verify both files exist at the repo root and are readable. Do not modify them in this step. The bootstrap prompt's Step 2 reading list depends on both being present.

---

## Scope out

- No business logic, no auth, no API client, no MSW config (those are 1.2 and 1.3)
- No custom palette tweaks (Step 1.4)
- No removing the default Next.js landing page (the next step's chrome scaffolding will replace it)
- No GitHub setup, no CI, no deployment config

---

## Acceptance criteria

1. `pnpm dev` runs without errors
2. `http://localhost:3000` renders the default Next.js page in dark mode
3. `pnpm tsc --noEmit` exits zero
4. `package.json` lists all dependencies above with reasonable versions
5. `tsconfig.json` has strict mode and the two extra strict flags
6. shadcn/ui is initialised and the listed primitives are present in `components/ui/`
7. `.env.example` and `.env.local` exist with the listed variables
8. `README.md` exists at repo root and is readable
9. `BUILD_PLAN.md` exists at repo root and is readable
10. `BUILD_PLAN.md` has Step 1.1 flipped to DONE

---

## After completing the step

Per the bootstrap working rules:

1. Confirm acceptance criteria
2. Report changes (files added, lines roughly, deps added)
3. Update `BUILD_PLAN.md` Step 1.1 status to DONE
4. Propose a git commit:
   ```
   git add -A
   git commit -m "Step 1.1: Next.js scaffold with stack installed; README and BUILD_PLAN present"
   ```
5. Wait for user direction before starting Step 1.2

---

## If you hit a snag

- Scaffold prompts for an option not covered above: ask the user, mark the question `Q1/N`
- A dependency fails to install: report exact error, do not retry blindly
- TypeScript strict reveals issues in scaffolded code: investigate, do not suppress with `any`. If unavoidable, flag and ask
- Tailwind config differs from what shadcn expects: read both configs, propose a merge, ask before committing
