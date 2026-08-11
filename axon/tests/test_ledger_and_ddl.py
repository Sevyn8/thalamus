"""The ledger's statement and the DDL's constraints, checked against the artifacts themselves.

WHAT THIS FILE CANNOT COVER, stated rather than left to be assumed: none of these run against a
real Postgres, so nothing here proves a CHECK constraint fires, an RLS policy refuses a write, or
a grant applies. Those are properties of the applied schema and the VERIFY block in
infra/db-setup/sql/06_axon_sender_grant.sql is their manual form. What these DO cover is the
class of defect this project keeps paying for: an artifact that says one thing while a sibling
artifact says another.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from axon import DeliveryState, SuppressionReason
from axon import ledger as ledger_module

_DDL = Path(__file__).resolve().parents[1] / "schemas" / "postgres" / "deliveries.sql"
_GRANT = Path(__file__).resolve().parents[2] / "infra" / "db-setup" / "sql" / "06_axon_sender_grant.sql"


def test_the_artifacts_are_where_this_test_thinks_they_are() -> None:
    """THE VACUITY GUARD, and it is not ceremony. Every check below reads a file; a path that
    stopped resolving would make all of them pass against an empty string."""
    assert _DDL.is_file(), f"{_DDL} not found"
    assert _GRANT.is_file(), f"{_GRANT} not found"
    assert "CREATE TABLE IF NOT EXISTS axon.platform_deliveries" in _DDL.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# THE STATEMENT. What it must not contain is the whole point.
# ---------------------------------------------------------------------------


def test_the_insert_has_no_on_conflict_and_no_returning() -> None:
    """SLICE 5e IN ADVANCE. Both need SELECT, and axon_sender holds none.

    ON CONFLICT must read the arbiter index to detect the conflict. RETURNING must read the row
    it returns. The role has neither privilege, deliberately, because the send path performs zero
    reads and a credential that cannot read cannot leak a ledger of who was contacted about what.

    5e shipped ON CONFLICT against a role with no SELECT and every enable in production failed
    with `permission denied for table provision` from deploy until it was found. This is that
    defect refused before it can be written.
    """
    sql = str(ledger_module._INSERT_PLATFORM).upper()
    assert "ON CONFLICT" not in sql, (
        "ON CONFLICT needs SELECT on the arbiter index and axon_sender holds none. "
        "ledger.py's docstring names the two mechanisms that work."
    )
    assert "RETURNING" not in sql, "RETURNING needs SELECT; the caller mints the id instead"
    assert "SELECT" not in sql, "the send path performs zero reads, which is why the grant is INSERT only"


def test_the_statement_writes_only_the_platform_ledger() -> None:
    """ONE TABLE. The tenant ledger ships ungranted, and a statement naming it would be a write
    this role cannot make and a session posture nothing here opens."""
    sql = str(ledger_module._INSERT_PLATFORM)
    assert "axon.platform_deliveries" in sql
    assert "tenant_deliveries" not in sql


def test_the_statement_does_not_name_template_version_id() -> None:
    """The platform table CHECK-forces it NULL, so naming it in the column list would be writing
    the value the constraint exists to refuse. The column is on the table only to keep ONE column
    list across the audience pair, which is what makes a merged read a plain UNION."""
    assert "template_version_id" not in str(ledger_module._INSERT_PLATFORM)


# ---------------------------------------------------------------------------
# THE VOCABULARIES. Python and the CHECK constraints must agree.
# ---------------------------------------------------------------------------


def test_the_state_vocabulary_matches_the_check_constraint() -> None:
    """TWO ARTIFACTS, ONE VOCABULARY. A Python enum wider than the CHECK produces a constraint
    violation after the send already happened; narrower, and a legal row is unrepresentable in
    the code that writes it."""
    ddl = _DDL.read_text(encoding="utf-8")
    match = re.search(r"ck_platform_deliveries_state_vocab\s*\n?\s*CHECK \(state IN \(([^)]*)\)\)", ddl)
    assert match is not None, "the state CHECK is gone or was reshaped; this guard has stopped biting"
    in_ddl = {value.strip().strip("'") for value in match.group(1).split(",")}
    assert in_ddl == {member.value for member in DeliveryState}


def test_the_suppression_vocabulary_matches_the_check_constraint() -> None:
    """Same pairing, and this one matters MORE because none of the four is reachable yet. An
    unreachable vocabulary is exactly the kind that drifts unnoticed until the day it is used."""
    ddl = _DDL.read_text(encoding="utf-8")
    pattern = (
        r"ck_platform_deliveries_suppression_vocab\s*\n?\s*"
        r"CHECK \(suppression_reason IS NULL OR suppression_reason IN \(\s*([^)]*)\)"
    )
    match = re.search(pattern, ddl)
    assert match is not None, "the suppression CHECK is gone or was reshaped"
    in_ddl = {value.strip().strip("'") for value in match.group(1).split(",") if value.strip()}
    assert in_ddl == {member.value for member in SuppressionReason}


def test_accepted_is_not_called_sent() -> None:
    """THE STATE NAME IS THE GUARD. A provider's success code is ACCEPTANCE: SendGrid answers 202
    and the mail may still bounce, be filtered or be dropped, and nothing in this platform will
    know until an inbound receipt plane exists.

    A state called `sent` or `delivered` would make every future reader of this ledger believe
    something it cannot support.
    """
    values = {member.value for member in DeliveryState}
    assert "accepted" in values
    assert "sent" not in values
    assert "delivered" not in values


def test_there_is_no_queued_state_until_there_is_a_queue() -> None:
    """Nothing can produce it: the row is written after the provider answers. It arrives with the
    queue, and it arrives together with the UPDATE grant that moving a row between states needs.
    A state nothing can write is a state a reader will wrongly believe is reachable."""
    assert "queued" not in {member.value for member in DeliveryState}


# ---------------------------------------------------------------------------
# THE DDL's OWN INVARIANTS
# ---------------------------------------------------------------------------


def test_the_platform_ledger_is_email_only_by_constraint() -> None:
    """EXPRESSED AS A CHECK, NOT A CONVENTION, on the rung's argument: a value that cannot be
    written cannot be mistyped. Sevyn8's own traffic has no WABA, no DLT registration and no
    approved templates, because those belong to a TENANT."""
    ddl = _DDL.read_text(encoding="utf-8")
    assert "ck_platform_deliveries_email_only" in ddl
    assert "CHECK (channel = 'email')" in ddl


def test_the_tenant_ledger_is_multi_channel_and_force_rls() -> None:
    """The pair's whole reason for existing. The tenant table must NOT inherit the email-only
    constraint, and it must carry FORCE so the policy binds the owner too."""
    ddl = _DDL.read_text(encoding="utf-8")
    assert "ck_tenant_deliveries_channel_vocab" in ddl
    assert "CHECK (channel IN ('email', 'whatsapp', 'sms'))" in ddl
    assert "ALTER TABLE axon.tenant_deliveries ENABLE ROW LEVEL SECURITY" in ddl
    assert "ALTER TABLE axon.tenant_deliveries FORCE ROW LEVEL SECURITY" in ddl


def test_the_tenant_policy_widens_reads_and_pins_writes() -> None:
    """THE ONE DELIBERATE DIVERGENCE FROM CM'S AUDIT PAIR, PINNED SO IT IS NOT "FIXED" BACK.

    USING carries the unconditional PLATFORM branch, so a PLATFORM session READS every tenant's
    deliveries, which a fleet-wide console needs. WITH CHECK does NOT, so a WRITE must name the
    tenant whose session it runs in.

    CM's tenant_activity_audit_logs puts the branch in both halves, which lets a PLATFORM session
    write a row naming any tenant. For a sender writing in a loop on behalf of many tenants, that
    is precisely the bug: one delivery recorded against the wrong customer, invisible in the
    sending path, refused by nothing.
    """
    ddl = _DDL.read_text(encoding="utf-8")
    policy = ddl[ddl.index("CREATE POLICY tenant_deliveries_tenant_isolation") :]
    using = policy[policy.index("USING (") : policy.index("WITH CHECK (")]
    with_check = policy[policy.index("WITH CHECK (") :]

    assert "current_setting('app.user_type', TRUE) = 'PLATFORM'" in using, (
        "the PLATFORM read branch is gone; a fleet-wide console read would return nothing"
    )
    assert "current_setting('app.user_type', TRUE) = 'PLATFORM'" not in with_check, (
        "the PLATFORM branch reached WITH CHECK. A platform session could then write a delivery "
        "naming ANY tenant, which is the failure a sender writing for many tenants produces. "
        "Read the argument above the policy before changing this."
    )
    assert "NULLIF(current_setting('app.tenant_id', TRUE), '')" in with_check, (
        "the NULLIF wrapper is gone; on a reused pooled connection the GUC is '' and ''::uuid raises"
    )


def test_the_grant_file_gives_the_sender_insert_and_nothing_else() -> None:
    """THE SECOND LAYER, read from the artifact that creates it. A code-only guarantee is one
    merge from being untrue."""
    grant = _GRANT.read_text(encoding="utf-8")
    assert "GRANT INSERT ON axon.platform_deliveries TO axon_sender;" in grant
    assert "GRANT USAGE ON SCHEMA axon TO axon_sender;" in grant

    # NO SELECT, ANYWHERE. This is what the whole read-nothing design buys.
    assert "GRANT SELECT" not in grant, (
        "a SELECT grant appeared. The send path performs zero reads; if something now needs one, "
        "the grant and the read must be justified together, not the grant alone."
    )
    # And nothing at all on the tenant ledger, which ships empty and ungranted.
    assert "REVOKE ALL ON axon.tenant_deliveries FROM axon_sender;" in grant
    assert "GRANT INSERT ON axon.tenant_deliveries" not in grant


@pytest.mark.parametrize("forbidden", ["UPDATE", "DELETE", "TRUNCATE"])
def test_the_grant_file_gives_the_sender_no_way_to_edit_a_record(forbidden: str) -> None:
    """A ledger that can be rewritten is not evidence of anything. This also means the inbound
    receipt slice cannot move a row from `accepted` to `delivered` with THIS role, which is
    correct: that slice brings its own grant and argues for it in the open."""
    grant = _GRANT.read_text(encoding="utf-8")
    assert f"GRANT {forbidden}" not in grant
