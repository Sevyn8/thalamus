# Thalamus shared-DB setup (Wave 1)

Privileged SQL that Terraform deliberately does NOT run, because the two steps
require the `cloudsqlsuperuser` (`postgres`) role and one of them depends on an
app migration having run first. Terraform owns the instance + database + roles;
these SQL files own extensions, the canonical `uuidv7()`, and the mirror-reader
grant.

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
5. **`sql/02_mirror_reader_grant.sql`** as `postgres`, connected to the shared
   database: grants `dis_mirror_reader` USAGE on `core` + SELECT on
   `core.tenants` / `core.stores`. MUST run after step 3 (references those
   tables).

Steps 3 and 4 are independent of each other and can run in either order once
step 2 is done. Step 5 depends only on step 3.

## Connecting as postgres to run the SQL

Both apps reach the instance over private IP. To run the setup SQL as `postgres`
you connect the same way (Cloud SQL Auth Proxy from a VM/Cloud Shell inside the
VPC, or Cloud SQL Studio as the `postgres` user). Example with the proxy:

```
# in one shell: proxy to the instance (connection name from the TF output)
cloud-sql-proxy <PROJECT>:asia-south1:thalamus-pg
# in another: run each file against the shared database as postgres
psql "host=127.0.0.1 dbname=thalamus user=postgres" -f sql/01_extensions_and_uuidv7.sql
psql "host=127.0.0.1 dbname=thalamus user=postgres" -f sql/02_mirror_reader_grant.sql   # step 5, after CM Alembic
```

## Folding note (flagged, not resolved this wave)

Each app's Alembic still contains its own extension / `uuidv7()` step
(DIS `00_extensions/uuidv7_setup.sql` + `btree_gist` in migration 0005; CM's
`shared_utilities` function). After step 2 those become redundant: extensions are
`IF NOT EXISTS` no-ops, and a `CREATE OR REPLACE FUNCTION` on `public.uuidv7()`
by an app role will fail on ownership (the function is owned by `postgres`). On
the shared instance those app-side steps should be treated as already-satisfied
(skipped) or made owner-safe. This is app-repo folding work, tracked for a later
wave, not resolved here.
