"""The tenant channel rails, checked against the DDL itself.

WHAT THIS FILE CANNOT COVER, stated first because it is unusually true here. None of these run
against a real Postgres. Nothing below proves a CHECK fires, a policy refuses a write, a trigger
sets a sequence number, or the composite foreign key rejects a cross-tenant reference. Axon's
suite is offline by design and NEITHER local container carries an axon schema, so
schemas/postgres/channels.sql is first EXECUTED by the migrate-axon job against staging.

The single exception is the foreign key's cross-tenant behaviour, which was executed for real in
a scratch schema before the DDL was written, and whose result is recorded at the constraint and
in migration 0002 rather than asserted here: a text assertion cannot re-run a probe.

WHAT THESE DO COVER is the class of defect this project keeps paying for: an artifact that says
one thing while a sibling artifact says another. The policy asymmetry, the vocabularies shared
with the ledger, the paired timestamps and the shape of the foreign key are all things a later
edit can quietly undo, and each of them is written down in exactly one place.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_SCHEMAS = Path(__file__).resolve().parents[1] / "schemas" / "postgres"
_CHANNELS = _SCHEMAS / "channels.sql"
_DELIVERIES = _SCHEMAS / "deliveries.sql"
_MIGRATION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0002_axon_channels.py"


def _channels() -> str:
    return _CHANNELS.read_text(encoding="utf-8")


def _channels_code() -> str:
    """channels.sql with every ``--`` comment stripped, so prose ABOUT a thing is not read as
    the thing.

    A GUARD THAT NAMES WHAT IT FORBIDS CANNOT SCAN ITSELF, and both checks that need this were
    written without it first and failed on their own explanations: the file argues at length
    that nothing is GRANTed and that ``ADD CONSTRAINT IF NOT EXISTS`` is not valid SQL, so a raw
    scan reported the argument as the violation. Same shape and same reason as
    axon-sender's test_deployment_posture._terraform_code.

    Line-oriented and deliberately simple: this file has no dollar-quoted string containing a
    double hyphen, and if one ever appears the tests that use this helper get louder, not
    quieter.
    """
    return "\n".join(line.split("--")[0] for line in _channels().splitlines())


def test_the_artifacts_are_where_this_test_thinks_they_are() -> None:
    """THE VACUITY GUARD. Every check below reads a file; a path that stopped resolving would
    make all of them pass against an empty string, and this file would report a clean run
    having compared nothing."""
    assert _CHANNELS.is_file(), f"{_CHANNELS} not found"
    assert _DELIVERIES.is_file(), f"{_DELIVERIES} not found"
    assert _MIGRATION.is_file(), f"{_MIGRATION} not found"
    assert "CREATE TABLE IF NOT EXISTS axon.channel_connections" in _channels()
    assert "CREATE TABLE IF NOT EXISTS axon.channel_templates" in _channels()


# ---------------------------------------------------------------------------
# THE POLICY ASYMMETRY, ON BOTH NEW TABLES. Same test as the ledger's, twice.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "policy_name",
    ["channel_connections_tenant_isolation", "channel_templates_tenant_isolation"],
)
def test_each_policy_widens_reads_and_pins_writes(policy_name: str) -> None:
    """COPIED VERBATIM FROM THE LEDGER'S POLICY, AND PINNED SO IT IS NOT "FIXED" BACK.

    USING carries the unconditional PLATFORM branch, so a PLATFORM session reads every tenant's
    connection state, which is the fleet-wide operator question these tables exist to answer.
    WITH CHECK does not, so a WRITE must name the tenant whose session it runs in.

    The failure the asymmetry prevents is the same one the ledger names: a writer looping over
    tenants records one tenant's row against another, invisibly, refused by nothing. It is worse
    here than on the ledger, because the row being misfiled carries a credential REFERENCE.
    """
    ddl = _channels()
    policy = ddl[ddl.index(f"CREATE POLICY {policy_name}") :]
    using = policy[policy.index("USING (") : policy.index("WITH CHECK (")]
    with_check = policy[policy.index("WITH CHECK (") :]
    # Bound WITH CHECK at the statement's end so a LATER policy in the same file cannot be
    # read as part of this one and make the negative assertion below pass by accident.
    with_check = with_check[: with_check.index(";")]

    assert "current_setting('app.user_type', TRUE) = 'PLATFORM'" in using, (
        f"{policy_name} lost its PLATFORM read branch; a fleet-wide console read returns nothing"
    )
    assert "current_setting('app.user_type', TRUE) = 'PLATFORM'" not in with_check, (
        f"the PLATFORM branch reached {policy_name}'s WITH CHECK. A platform session could then "
        "write a row naming ANY tenant. Read the argument above the policy before changing this."
    )
    assert "NULLIF(current_setting('app.tenant_id', TRUE), '')" in with_check, (
        "the NULLIF wrapper is gone; on a reused pooled connection the GUC is '' and ''::uuid raises"
    )


@pytest.mark.parametrize(
    ("policy_name", "table"),
    [
        ("channel_connections_tenant_isolation", "channel_connections"),
        ("channel_templates_tenant_isolation", "channel_templates"),
    ],
)
def test_each_policy_is_dropped_before_it_is_created(policy_name: str, table: str) -> None:
    """`CREATE POLICY IF NOT EXISTS` DOES NOT EXIST IN POSTGRES, AND THIS FILE FOUND OUT BY
    RUNNING.

    Every DDL file in this chain is required to be hand-runnable and repeatable, which 0001
    states as its contract. CREATE TABLE IF NOT EXISTS delivers that for the tables and does
    nothing for the policies: applying channels.sql twice failed the second time with
    `policy "..." for table "..." already exists`.

    The DROP is what makes the file idempotent, and it is invisible: somebody adding a third
    policy will copy the CREATE and not the line above it. That is the drift this asserts.

    axon/schemas/postgres/deliveries.sql HAS THE SAME DEFECT and is deliberately not fixed
    here: it is outside this slice's scope. It has never bitten because alembic applies a
    revision once, and it will bite the first person who hand-runs that file twice.
    """
    code = _channels_code()
    drop = f"DROP POLICY IF EXISTS {policy_name} ON axon.{table};"
    create = f"CREATE POLICY {policy_name}"
    assert drop in code, (
        f"{policy_name} is created without being dropped first, so a second run of "
        "channels.sql fails. There is no CREATE POLICY IF NOT EXISTS to reach for."
    )
    assert code.index(drop) < code.index(create), "the DROP must precede the CREATE"


@pytest.mark.parametrize("table", ["channel_connections", "channel_templates"])
def test_each_table_forces_row_level_security(table: str) -> None:
    """ENABLE alone leaves the OWNER exempt, and Axon's chain runs as the owner. Without FORCE
    the isolation is a property of who happens to connect."""
    ddl = _channels()
    assert f"ALTER TABLE axon.{table} ENABLE ROW LEVEL SECURITY" in ddl
    assert f"ALTER TABLE axon.{table} FORCE ROW LEVEL SECURITY" in ddl


# ---------------------------------------------------------------------------
# VOCABULARIES SHARED WITH THE LEDGER, rather than a second copy free to drift.
# ---------------------------------------------------------------------------


def test_the_channel_vocabulary_matches_the_ledgers_exactly() -> None:
    """A channel the ledger can RECORD must be one these tables can DESCRIBE. Two vocabularies
    for one concept is how a legal delivery becomes an unrepresentable connection."""
    ledger_check = "CHECK (channel IN ('email', 'whatsapp', 'sms'))"
    assert ledger_check in _DELIVERIES.read_text(encoding="utf-8")
    assert _channels().count(ledger_check) == 2, (
        "both new tables must carry the ledger's channel vocabulary verbatim; one of them has "
        "drifted, which makes a channel describable on one table and not the other"
    )


def test_the_join_columns_keep_the_ledgers_widths() -> None:
    """notification_class is the join key deliveries.sql names, and channel joins too. A
    narrower column here truncates silently on the join rather than raising."""
    ddl = _channels()
    assert 'notification_class      VARCHAR(64) COLLATE "C"' in ddl, (
        "notification_class is no longer VARCHAR(64); the ledger's column is, and a mismatch "
        "truncates on the join that resolves a template"
    )
    assert ddl.count('channel             VARCHAR(16) COLLATE "C"') >= 1
    assert ddl.count('channel                 VARCHAR(16) COLLATE "C"') >= 1


def test_the_suppression_reason_is_not_redefined_here() -> None:
    """'no_approved_template' ALREADY EXISTS in both ledgers' vocabularies. This slice adds
    nothing to them, and a second definition would be the drift these tests exist to catch."""
    deliveries = _DELIVERIES.read_text(encoding="utf-8")
    assert deliveries.count("'no_approved_template'") == 2, (
        "the reason is meant to be in BOTH ledgers' suppression vocabularies already"
    )
    assert "ck_tenant_deliveries_suppression_vocab" not in _channels(), (
        "channels.sql is redefining the ledger's suppression vocabulary. It must not: the "
        "reason already exists and this file only makes it reachable."
    )


def test_the_unreachable_reason_is_declared_as_unreachable() -> None:
    """THE HONEST-ARTIFACT CHECK. 'no_approved_template' cannot be emitted today because nothing
    in send.py resolves a template. A registry that did not say so would read as if the reason
    were live, and somebody would go looking in the ledger for rows that cannot exist."""
    ddl = _channels()
    assert "no_approved_template" in ddl
    assert "UNREACHABLE" in ddl, (
        "channels.sql no longer states that the suppression reason is currently unreachable"
    )


# ---------------------------------------------------------------------------
# THE LIFECYCLE, which is config.source_mappings' and is carried for its reasons.
# ---------------------------------------------------------------------------


def test_the_status_vocabulary_is_the_four_state_lifecycle() -> None:
    assert "CHECK (status IN ('DRAFT', 'STAGED', 'ACTIVE', 'DEPRECATED'))" in _channels()


@pytest.mark.parametrize(
    "constraint",
    [
        "ck_channel_templates_activated_consistency",
        "ck_channel_templates_deprecated_consistency",
    ],
)
def test_each_lifecycle_timestamp_is_check_paired_to_the_status(constraint: str) -> None:
    """A timestamp that can disagree with the status it describes is a second source of truth
    about one fact. config.source_mappings pairs both by CHECK and so does this."""
    assert f"CONSTRAINT {constraint}" in _channels()


def test_at_most_one_active_per_resolution_key_not_per_template() -> None:
    """THE DELIBERATE DIVERGENCE FROM THE PRECEDENT, PINNED.

    config.source_mappings keys its partial unique index on (tenant_id, source_id, template_id):
    one ACTIVE per TEMPLATE. Keyed that way here, two ACTIVE rows could answer one (tenant,
    channel, class) question as long as they belonged to different templates, and the send path
    would have no way to choose. The index must match the question that gets asked.
    """
    ddl = _channels()
    index = ddl[ddl.index("CREATE UNIQUE INDEX IF NOT EXISTS uq_channel_templates_active_per_class") :]
    index = index[: index.index(";")]
    assert "(tenant_id, channel, notification_class)" in index, (
        "the ACTIVE index no longer keys on the resolution key. If it keys on template_id, two "
        "ACTIVE rows can answer one send-path question."
    )
    assert "WHERE status = 'ACTIVE'" in index, (
        "the index is no longer partial, so it forbids more than one version per key entirely, "
        "which is the lifecycle this table exists to support"
    )


def test_the_label_guard_permits_two_versions_of_one_template() -> None:
    """WHY IT IS AN EXCLUDE AND NOT A UNIQUE INDEX, asserted rather than commented.

    During a shadow rollout an ACTIVE v1 and a STAGED v2 of ONE template legitimately share a
    label. A plain unique index would refuse that, which is the normal case, and a guard that
    forbids the normal case is one somebody removes. `template_id WITH <>` is the whole point.
    """
    ddl = _channels()
    assert "CONSTRAINT ex_channel_templates_label_per_class" in ddl
    assert "EXCLUDE USING gist" in ddl
    assert "template_id WITH <>" in ddl, (
        "the EXCLUDE no longer permits two versions of ONE template to share a label, which is "
        "the shadow-rollout case the lifecycle exists for"
    )
    assert "WHERE (status <> 'DEPRECATED')" in ddl


def test_the_gist_extension_is_declared_in_the_file_that_needs_it() -> None:
    """The EXCLUDE needs btree_gist for its equality operator classes. Declared in this file so
    a hand-run works, and so the failure is a loud one in the same transaction rather than a
    table created without its guard."""
    ddl = _channels()
    assert "CREATE EXTENSION IF NOT EXISTS btree_gist" in ddl
    assert ddl.index("CREATE EXTENSION IF NOT EXISTS btree_gist") < ddl.index(
        "CONSTRAINT ex_channel_templates_label_per_class"
    ), "the extension must be created before the constraint that needs it"


# ---------------------------------------------------------------------------
# THE COMPOSITE FOREIGN KEY. Its shape is the whole finding.
# ---------------------------------------------------------------------------


def test_the_foreign_key_is_composite_and_not_single_column() -> None:
    """THE MEASURED RESULT, PINNED SO IT CANNOT BE SIMPLIFIED BACK.

    The single-column form was built against a real Postgres with both tables FORCE RLS and a
    NOSUPERUSER NOBYPASSRLS writer, and it ACCEPTED a tenant-A delivery pinning a tenant-B
    template version: referential-integrity checks bypass row level security. The composite form
    rejected the same insert. A future reader simplifying this to one column would restore a
    cross-tenant write that looks guarded.
    """
    ddl = _channels()
    assert "FOREIGN KEY (tenant_id, template_version_id)" in ddl, (
        "the foreign key is no longer composite. The single-column form was TESTED and permits "
        "one tenant's delivery to pin another tenant's template version."
    )
    assert "REFERENCES axon.channel_templates (tenant_id, template_version_id)" in ddl


def test_the_foreign_keys_target_constraint_exists_and_precedes_it() -> None:
    """A two-column reference needs a two-column UNIQUE to point at, and ordering inside the
    file is what makes a hand-run work. The UNIQUE is declared inline on the table, so it exists
    at CREATE TABLE time and the ALTER cannot outrun it."""
    ddl = _channels()
    assert "CONSTRAINT uq_channel_templates_tenant_version" in ddl
    assert "UNIQUE (tenant_id, template_version_id)" in ddl
    assert ddl.index("uq_channel_templates_tenant_version") < ddl.index(
        "ADD CONSTRAINT fk_tenant_deliveries_template"
    ), "the FK's target constraint must be created before the ALTER that references it"


def test_the_alter_is_guarded_and_the_guard_raises_when_it_misses() -> None:
    """`ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS` IS NOT VALID SQL. It was tried; Postgres
    answers `syntax error at or near "NOT"`. So the idempotency this chain requires of every DDL
    file has to be an explicit existence check, and a check whose condition stopped matching
    would skip the ALTER and leave a migration that succeeded with no foreign key. The RAISE is
    what turns that into a failure."""
    code = _channels_code()
    assert "ADD CONSTRAINT IF NOT EXISTS" not in code, (
        "that syntax does not exist in Postgres; the DO block is the only working form"
    )
    assert "RAISE EXCEPTION" in code, (
        "the post-condition is gone. Without it a mistyped guard skips the ALTER silently."
    )
    # And the explanation must survive in the COMMENTS, because the next person to try that
    # syntax needs the answer next to the workaround rather than in a test.
    assert "ADD CONSTRAINT IF NOT EXISTS" in _channels()


def test_the_platform_ledger_takes_no_foreign_key() -> None:
    """It has no tenant_id to compose a two-column reference from, and its own CHECK already
    forces the column NULL. An FK there would be unwritable and unnecessary in that order."""
    ddl = _channels()
    assert "ALTER TABLE axon.platform_deliveries" not in ddl
    assert "ck_platform_deliveries_no_template" in _DELIVERIES.read_text(encoding="utf-8")


def test_template_version_id_stays_nullable() -> None:
    """Every existing row is NULL and email traffic legitimately has no approved template. A
    NOT NULL in this slice would refuse the only traffic that exists."""
    deliveries = _DELIVERIES.read_text(encoding="utf-8")
    assert "template_version_id     BIGINT                              NULL" in deliveries
    assert "SET NOT NULL" not in _channels()


# ---------------------------------------------------------------------------
# THE ABSENCES, which are decisions and are asserted as such.
# ---------------------------------------------------------------------------


def test_the_registry_ships_empty() -> None:
    """NO SEEDED ROW, in the DDL or the migration. Three names exist for the first tenant and
    none can be verified until an adapter can attempt a send. A wrong seeded name fails at the
    provider; an empty table suppresses with a reason somebody can read."""
    assert "INSERT INTO axon.channel_templates" not in _channels()
    assert "INSERT INTO" not in _MIGRATION.read_text(encoding="utf-8")


def test_neither_table_is_granted_to_anything() -> None:
    """SLICE 1'S RECORDED PRECEDENT. A grant arrives with the code that needs it and with the
    session posture that code must open. Nothing reads these tables and nothing writes them, so
    a grant now would be a credential reaching a table no code opens a session against."""
    migration = _MIGRATION.read_text(encoding="utf-8")
    for table in ("channel_connections", "channel_templates"):
        assert f"GRANT SELECT ON axon.{table}" not in migration
        assert f"GRANT INSERT ON axon.{table}" not in migration
    assert "GRANT" not in _channels_code(), (
        "channels.sql is granting something. Grants live in numbered files or in the migration, "
        "and this slice has decided there are none."
    )


def test_the_credential_itself_is_not_a_column() -> None:
    """SEVYN8 NEVER HOLDS ANOTHER COMPANY'S CREDENTIAL. The table carries a NAME, and a future
    console query cannot leak a value that is not in the row."""
    code = _channels_code().lower()
    assert "secret_ref" in code
    for forbidden in ("password", "client_secret", "credential_value", "api_key", "access_token"):
        assert forbidden not in code, (
            f"a column named {forbidden!r} reached the executable DDL. The credential is the "
            "tenant's, it lives in Secret Manager, and only its NAME belongs in this table."
        )


def test_the_on_conflict_trap_is_recorded_where_the_writer_will_read_it() -> None:
    """(f)6, WRITTEN DOWN RATHER THAN REPORTED. The natural writer is an upsert on
    (tenant_id, channel); ON CONFLICT reads the arbiter index, which is a SELECT the sender's
    role does not hold. That cost slice 5e two days and it will cost the next slice the same
    unless the warning is in the table it applies to."""
    ddl = _channels()
    assert "ON CONFLICT" in ddl and "5e" in ddl and "06_axon_sender_grant.sql" in ddl, (
        "the ON CONFLICT warning naming 5e and the grant file has gone from channel_connections"
    )


def test_only_pending_is_declared_reachable() -> None:
    """The state name is the guard, exactly as `accepted` is not called `sent` on the ledger.
    Nothing can observe a connection working until an adapter can send on it."""
    ddl = _channels()
    assert "CHECK (status IN ('pending', 'connected', 'disabled'))" in ddl
    assert "ONLY 'pending' IS REACHABLE TODAY" in ddl
