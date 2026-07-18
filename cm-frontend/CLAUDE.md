@AGENTS.md
@PATTERNS.md

## Critical references for backend wiring (Phase 4b onward)

- `docs/frontend-backend-wiring-handoff.md` — Sanjeev's handoff doc; canonical contract reference for backend wiring. Read before any wiring work, type-regen, or auth-refactor edits.
- `docs/openapi.json` — machine-readable backend OpenAPI spec. Backend-shape TypeScript types are generated from this file (Phase 4b Chunk 3 onward via `openapi-typescript`); do not hand-edit the generated types. Hand-maintained types remain only for frontend-only concerns (UI state, component props).

Phase 4b decision (2026-05-04): backend is source of truth. When the frontend disagrees with the backend's contract, the frontend adjusts.
