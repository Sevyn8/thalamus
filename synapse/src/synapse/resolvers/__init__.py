"""The ONLY Synapse package that may name or reach a canonical table.

Every resolver is READ-ONLY on canonical (Synapse never writes a DIS table) and takes
its engine by INJECTION — this package constructs no engine and reads no DSN from the
environment.

THE ROLE IS DEFERRED, AND DELIBERATELY NOT ``ithina_dis_user``. That role holds full
DML on canonical; handing it to a read-only analytics plane is the same mistake as
pointing mirror-sync at ``cm-database-url`` instead of ``dis_mirror_reader``, which
this project rejected on exactly those grounds. The intended identity is a
``synapse_reader``: USAGE on ``canonical``, SELECT on named tables only, NOSUPERUSER
NOBYPASSRLS — the ``dis_mirror_reader`` pattern. Provisioning it is terraform and is
the first infra item of the next slice; until then the integration test SKIPS without
a DSN rather than borrowing a writer's credentials.
"""
