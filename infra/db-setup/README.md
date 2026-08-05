# Thalamus shared-DB setup (Wave 1)

SQL that Terraform deliberately does NOT run. `sql/01` needs the
`cloudsqlsuperuser` (`postgres`) role (CREATE EXTENSION + a function in public);
`sql/02` needs `user_admin_backend` (the owner of `core`) and depends on CM's
migration having run first. Terraform owns the instance + database + roles; these
SQL files own extensions, the canonical `uuidv7()`, and the mirror-reader grant.

## Why not run these from Terraform

`CREATE EXTENSION` and creating a function in `public` require the
`cloudsqlsuperuser` role; the app roles are `NOSUPERUSER NOBYPASSRLS` by design.
An in-Terraform `local-exec` psql would need the Cloud SQL Auth Proxy running and
the `postgres` password wired into Terraform state, which is more fragile than a
documented one-time psql. So these are run by hand (or a CI step) as `postgres`.
The mirror-reader grant additionally cannot run until CM's Alembic has created
`core.tenants` / `core.stores`, so it is sequenced after CM's migration, not at
instance-create.

## Exact run order (hard dependencies)

1. **Terraform apply** (`infra/envs/staging`): creates the VPC, the Cloud SQL
   instance, the shared database, and the three roles
   (`user_admin_backend`, `ithina_dis_user`, `dis_mirror_reader`).
2. **`sql/01_extensions_and_uuidv7.sql`** as `postgres`, connected to the shared
   database: creates `vector`, `ltree`, `pgcrypto`, `btree_gist`, and the
   canonical `public.uuidv7()`. Run BEFORE any Alembic so each app's own
   extension / uuidv7 step is a no-op precondition.
3. **CM Alembic** (`admin-backend`, `DATABASE_URL` -> the shared DB as
   `user_admin_backend`): creates the `core` schema + CM tables (incl.
   `core.tenants`, `core.stores`) and self-grants to `user_admin_backend`.
4. **DIS Alembic** (`ithina-retail-dis`, `POSTGRES_URL` -> the shared DB as
   `ithina_dis_user`): creates DIS's 8 schemas (`audit`, `bronze`, `canonical`,
   `config`, `identity_mirror`, `quarantine`, `staging`, `telemetry`) and
   self-grants to `ithina_dis_user`.
5. **`sql/02_mirror_reader_grant.sql`** as `user_admin_backend` (owner of core),
   connected to the shared database: grants `dis_mirror_reader` USAGE on `core` +
   SELECT on `core.tenants` / `core.stores`. MUST run after step 3 (references
   those tables). NOT as `postgres`: Cloud SQL's cloudsqlsuperuser does not own
   core and cannot GRANT on it (fails with 'permission denied for schema core').

Steps 3 and 4 are independent of each other and can run in either order once
step 2 is done. Step 5 depends only on step 3.

**Status (2026-07-20, against the shared `thalamus` DB):** steps 1-5 completed.
sql/01 ran as `postgres`; CM Alembic as `user_admin_backend` (core + 15 tables);
DIS Alembic as `postgres` (8 schemas + 18 revisions); sql/02 as
`user_admin_backend` (dis_mirror_reader has exactly SELECT on core.tenants and
core.stores).

## Standing convention: PLATFORM scope for any file that reads a row

**Every hand-run SQL file in this directory that reads or writes a FORCE RLS
table opens with `set_config('app.user_type', 'PLATFORM', true)` inside a
transaction — unconditionally, as a convention, not as a per-file judgement.**

The failure this prevents is silent. Canonical's tables, `synapse.actions`,
`synapse.provision` and `synapse.run` are all `FORCE ROW LEVEL SECURITY`, so a
session with no `app.user_type` matches **zero rows and raises nothing**. FORCE
means owning the table buys nothing, and Cloud SQL's `postgres` is `rolsuper=f,
rolbypassrls=f` like any other role — so the trap applies to the most privileged
credential anyone runs these with.

Three situations then look identical at a psql prompt, and only one is loud:

| cause | what you see |
|---|---|
| missing GRANT | `ERROR: permission denied` — loud |
| **GUCs not set** | **0 rows, silently** |
| genuinely no data | 0 rows, silently |

This is a convention rather than advice because advice has already failed. It
has bitten four hand-written queries in this repo — a trigger test whose UPDATE
matched no visible row, migration 0002's DELETE, the provisioning pre-flight, and
a verification snippet in `sql/04` — and **every one was written by someone who
had already documented the trap elsewhere in this same repo.** Knowing about it
does not work. Opening the file with the set_config does.

Two details that matter:

- **`app.tenant_id` too, if the file WRITES.** PLATFORM widens *reads* only. Every
  policy's `WITH CHECK` still compares against the tenant GUC, so an INSERT under
  PLATFORM alone fails with `new row violates row-level security policy`.
- **Transaction-local (`true`), inside `BEGIN … COMMIT`.** A `false` third argument
  would leak the scope into whatever the operator does next in that session.

`provision_analysis.sql` is the worked example. Migration `0002` is the same
shape in Python.

## Connecting to run the SQL

The instance is private IP only. Connect via the Cloud SQL Auth Proxy (from a
VM/Cloud Shell inside the VPC) or Cloud SQL Studio. `sql/01` runs as `postgres`;
`sql/02` runs as `user_admin_backend`. Example with the proxy:

```
# in one shell: proxy to the instance (connection name from the TF output)
cloud-sql-proxy <PROJECT>:asia-south1:thalamus-pg
# in another: sql/01 as postgres (extensions + public.uuidv7())
psql "host=127.0.0.1 dbname=thalamus user=postgres" -f sql/01_extensions_and_uuidv7.sql
# sql/02 as user_admin_backend, AFTER CM Alembic (owner of core; postgres cannot GRANT on core)
psql "host=127.0.0.1 dbname=thalamus user=user_admin_backend" -f sql/02_mirror_reader_grant.sql
```

## Folding note (verified against the live shared DB, 2026-07-20)

Each app's Alembic still contains its own extension / `uuidv7()` step
(DIS `00_extensions/uuidv7_setup.sql` + `btree_gist` in migration 0005; CM's
`shared_utilities` function). Against the shared DB these turned out to conflict
with NEITHER app, as actually run:

- **CM:** its `uuidv7()` create is UNQUALIFIED and, with search_path `core,public`,
  lands in `core` (owned by `user_admin_backend`). It creates `core.uuidv7()`,
  which coexists with the pre-created `public.uuidv7()`. No ownership conflict.
- **DIS:** its create is `public.uuidv7()`, but DIS runs migrations as `postgres`
  (`POSTGRES_ADMIN_URL=postgres`, `POSTGRES_DB=thalamus`), which OWNS
  `public.uuidv7()` (created by `sql/01`), so `CREATE OR REPLACE` succeeds.
- Both apps' `CREATE EXTENSION IF NOT EXISTS` are no-ops (extensions pre-created
  by `sql/01`).

Neither app needed a migration code change. No folding work is outstanding here.
