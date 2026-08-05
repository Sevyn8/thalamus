"""Synapse's read-only BFF. Serves the SUPERADMIN console; writes nothing, anywhere.

WHY A PYTHON SERVICE RATHER THAN NEXT.JS ROUTE HANDLERS. Two of the five screens read the
REGISTRY, not the database: the capability list, the analysis list, every threshold and every
``stands_in_for`` sentence are Python object state produced by ``synapse.registry``'s import-time
checks. A TypeScript handler cannot reach them, and restating them in TS would create a second
source of truth for what Synapse can do — which would drift on the first slice that adds a
capability and be wrong in the one place an operator goes to find out.

The console itself is IN-SHELL: Next.js routes inside cm-frontend, beside Tenants and Stores,
because nine read-only superadmin screens viewed by the same person from the same session are
the same kind of thing. DIS went external because it is a large tenant-facing product; that
precedent does not transfer.

==============================================================================
THIS SERVICE HAS NO WRITER CREDENTIAL, AND THAT IS A DESIGN DECISION
==============================================================================
It is given ``SYNAPSE_READER_URL`` and nothing else. There is no writer DSN in its config, no
writer engine in ``db``, and no code path that could open one.

Slice 8a is read-only, so a service that merely *chose* not to write would be equivalent in
behaviour. It is not equivalent in property: the same argument that made two roles worth having
in slice 5 — ``synapse_writer`` holding INSERT and no SELECT, so "resolvers never write" is a
runtime fact rather than a grep — applies one layer up. A service that CANNOT write cannot be
made to write by a bug, a merge, or a future contributor in a hurry.

**Slice 8b must add the writer deliberately.** It will need one for provisioning (R3/R4/R5), and
adding it should be a visible act with its own review, not the discovery that it was already
wired and unused.

==============================================================================
ONE DISCRIMINATOR: ``user_type``. THERE WILL BE NO SYNAPSE EQUIVALENT OF ``dis:ops``.
==============================================================================
Every route here is PLATFORM-only, decided by the ``user_type`` claim Customer Master's Auth0
Action already stamps (``https://sevyn8.com/user_type``), which cm-frontend reads in
``lib/auth/jwt-decode.ts``.

dis-ui-server requires BOTH ``user_type=PLATFORM`` AND a ``dis:ops`` role, described there as
defence in depth. This project's ledger records the cost: two answers to one question, agreeing
today and diverging under impersonation. The fix is ONE answer — and that only holds if nobody
adds a second later. So it is written here rather than merely done: **no role claim will be
introduced as a second gate on these routes.** If a finer distinction is ever needed it replaces
``user_type``, it does not join it.

==============================================================================
NOT PUBLIC. Called server-side by cm-frontend; the browser never reaches it.
==============================================================================
Next.js server components fetch from here with a Google ID token minted from the metadata
server, so no Synapse data or token ever reaches the browser, there is no CORS surface, and the
Cloud Run invoker binding is IAM rather than ``allUsers``.

READ ``infra/modules/cloud-run-service-synapse-ui-server/main.tf`` BEFORE BELIEVING THAT THE
CALLER IS RESTRICTED. The binding removes ANONYMOUS access — the substance of the standing HIGH
finding — but cm-frontend has no dedicated service account and runs as the default compute
identity, which dis-ui-ver2 also runs as. The precise consequence is stated there.

==============================================================================
SCOPE, AND WHAT IS DELIBERATELY ABSENT
==============================================================================
IN  : fleet, one tenant, runs, capabilities, analyses. All PLATFORM, all read.
OUT : provisioning (needs a grant nothing holds), and the TENANT-facing view.

THE TENANT VIEW IS 8b's, AND ITS CONSTRAINT IS RECORDED IN ``tenant_view_contract`` IN THIS
PACKAGE rather than left to be rediscovered. It is the thing most likely to be got wrong under
time pressure, and getting it wrong destroys a holdout silently.
"""
