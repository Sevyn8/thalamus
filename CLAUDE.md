# Thalamus — rules for coding agents

These rules are durable. They exist so the repository keeps describing the system
that exists now, not how it was built.

## Ground rules

1. Read the current code, schemas, and tests before proposing or modifying
   architecture. Truth precedence: production code > database schema and
   migrations > machine-readable contracts (OpenAPI, JSON Schema) > tests >
   deployment configuration > prose documentation. Prose is never authoritative
   on its own; verify it against the implementation before relying on it.
2. No speculative future implementations. Do not write stubs, inert seams,
   placeholder modules, or `NotImplementedError` scaffolding for features that
   have no live requirement. Build a thing when it is needed, not before.
3. No placeholder services or directories for unbuilt features. A service
   directory exists only when it contains a working implementation.
4. Delete superseded implementations. Do not retain V1/V2 compatibility code,
   archived copies, or "old path" fallbacks without a live requirement. Git
   history is the archive.
5. Before adding a helper, client, model, or abstraction, search the repository
   for an existing implementation and use it. Duplication that already exists is
   consolidated only through an explicit architecture review, not opportunistically.
6. Do not introduce frameworks, managers, registries, factories, or wrapper
   layers to "organize" code. Prefer the plainest structure that works.

## Documentation

7. Repository documentation is exactly: `README.md`, `ARCHITECTURE.md`,
   `SECURITY.md`, `OPERATIONS.md`, and this file, plus the few retained
   exceptions that already exist (licences, normative contracts). Do not create
   new Markdown files unless the information genuinely belongs in none of these;
   update the root documents instead.
8. No build plans, phase/slice/step documents, session notes, handoff documents,
   progress reports, decision diaries, or completion status anywhere in the tree.
9. Comments and docstrings explain the current "why" — invariants, contracts,
   failure modes. Never development history ("X used to...", "changed in
   slice/step N"), never references to plans or process documents, and never
   instructions addressed to a future coding agent or mention of Claude,
   prompts, or sessions in product documentation or source comments.

## Safety rails

10. Preserve tenant isolation, RLS, and authentication/authorization boundaries.
    Any change touching row-level security, GUC session context, token
    verification, or tenant identity provenance requires tests proving both the
    allowed path and the denied path.
11. Never edit an applied database migration. New schema changes get new
    migrations; migration files are byte-for-byte immutable once merged.
12. Behavioral changes ship with tests in the same change. A test must prove the
    success path, not only the refusal path.
13. Do not change message acknowledgement, retry, idempotency, deduplication, or
    transaction semantics as a side effect of another change.
14. Run the subsystem's own gates (Makefile targets, package.json scripts)
    before declaring work done. There is no CI; the local gates are the gate.
