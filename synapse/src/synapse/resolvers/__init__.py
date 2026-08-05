"""The ONLY Synapse package that may name or reach a canonical table.

Every resolver is READ-ONLY on canonical (Synapse never writes a DIS table) and takes
its engine by INJECTION — this package constructs no engine and reads no DSN from the
environment.

TWO THINGS BESIDES RESOLVERS LIVE HERE, and both are here because they touch the database:

- ``_collapse`` — the D33 read-time latest-wins collapse, shared. **Any aggregate over a
  canonical event table must go through it**: the event tables are append-only, so a
  correction is two rows and ``SUM(...) GROUP BY ...`` over the raw table double-counts
  every one. The helper names no table itself, so it serves sale and change events alike.
- ``daily_series.probe_min_history_days`` — the MEASUREMENT half of a declared
  precondition. Preconditions are declared on the descriptor in ``synapse.core``, which is
  DB-free by contract; measuring one is a query, so it belongs here.

THE ROLE IS ``synapse_reader``, AND DELIBERATELY NOT ``ithina_dis_user``. That role holds
full DML on canonical; handing it to a read-only analytics plane is the same mistake as
pointing mirror-sync at ``cm-database-url`` instead of ``dis_mirror_reader``, which this
project rejected on exactly those grounds. ``synapse_reader`` holds USAGE on ``canonical``,
SELECT on exactly two CANONICAL tables — ``store_sku_current_position`` and
``store_sku_sale_events``, the only two any resolver here names — CONNECT on the database, and
SELECT on ``synapse.actions`` (slice 5, so the action log can be read back without an admin
credential). No write anywhere: appending is ``synapse_writer``'s, a separate role holding
INSERT and nothing else.

It is NOSUPERUSER NOBYPASSRLS, so canonical's FORCE RLS policies apply to it like any other
consumer, and dis-rls refuses on first use any engine whose role reports otherwise.

PROVISIONED AND VERIFIED AGAINST STAGING: Terraform's ``google_sql_user`` in cloud,
``dis/infra/local/postgres-init.sql`` on a fresh local volume, grants by
``infra/db-setup/sql/03_synapse_reader_grant.sql`` after Alembic. The integration tests run
as this role — that is what it exists for. SINCE SLICE 6a THE ORCHESTRATOR ALSO RUNS AS IT: it
is the identity that enumerates synapse.provision under PLATFORM scope and reads every canonical
row an analysis needs. So the sentence that stood here until now — "nothing in production runs as
it yet" — is retired. Nothing SCHEDULES the orchestrator yet, which is a different and smaller
claim; a hand-run is still a run.
"""
