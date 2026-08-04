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

THE ROLE IS DEFERRED, AND DELIBERATELY NOT ``ithina_dis_user``. That role holds full
DML on canonical; handing it to a read-only analytics plane is the same mistake as
pointing mirror-sync at ``cm-database-url`` instead of ``dis_mirror_reader``, which
this project rejected on exactly those grounds. The intended identity is a
``synapse_reader``: USAGE on ``canonical``, SELECT on named tables only, NOSUPERUSER
NOBYPASSRLS — the ``dis_mirror_reader`` pattern. Provisioning it is terraform and is
the first infra item of the next slice; until then the integration test SKIPS without
a DSN rather than borrowing a writer's credentials.
"""
