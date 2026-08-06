"""The durable action log: an APPENDER and a READER, deliberately separate objects.

Two classes rather than one, because there are two roles and they hold disjoint grants.
``synapse_writer`` has INSERT and no SELECT; ``synapse_reader`` has SELECT and no INSERT. A
single class carrying both operations would have one permanently unimplementable — and
``NotImplementedError`` for a method the grants forbid is a symptom, not a design.

So three layers now say the same thing: the GRANT says the writer cannot read, the ENGINE it is
handed says it, and the TYPE says it — ``PostgresActionAppender`` has no ``events()`` to call.
The same discipline as the DDL's generated columns, which make a row disagreeing with its own
target unrepresentable rather than merely detectable.

WHY THIS IS NOT IN ``synapse.core``. It constructs SQL, and ``synapse.core`` is forbidden
sqlalchemy by import-linter — the correct boundary, and the reason the action TYPES are pure and
this is not. ``synapse.persistence`` sits above the resolvers in the layers contract.

APPEND-ONLY, THREE TIMES OVER. This module constructs exactly two statement shapes, one INSERT
and one SELECT, and no method could construct another. The database enforces the same property
independently: ``synapse_writer`` holds INSERT only, and a ``BEFORE UPDATE OR DELETE`` trigger
raises for every role including the table owner.

IDEMPOTENT BY ``ON CONFLICT DO NOTHING`` over ``uq_actions_idempotency``. A retry reproduces the
payload, its hash collides, the insert is suppressed; a correction differs and lands as its own
row. Migration 0019's resolution of the same problem in canonical. It is here before anything
retries because adding uniqueness to a table that already holds duplicates is a cleanup rather
than a migration — which is exactly how 0019 went.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_rls import rls_session
from synapse.core.action import Action, ActionEvent, Provenance, Verb
from synapse.core.errors import ResultTooLargeError
from synapse.core.holdout import Arm

# The only two statements this module can produce. Written out rather than assembled, so both
# shapes are reviewable in one place and no code path can build a third.
#
# The three GENERATED columns (tenant_id, store_id, sku_id) are absent from the INSERT's column
# list because Postgres refuses a direct write to them — which is the whole point of deriving
# them from `target` instead of copying them alongside it.
_INSERT = text(
    """
    INSERT INTO synapse.actions (
        event_id, recorded_at, supersedes,
        target, verb, quantity_at_stake, expires_on, arm,
        declaration_id, declaration_version, capability_versions, thresholds, as_of,
        payload_hash,
        days_since_last_sale, days_of_cover
    ) VALUES (
        CAST(:event_id AS uuid), :recorded_at, CAST(:supersedes AS uuid),
        CAST(:target AS jsonb), :verb, :quantity_at_stake, :expires_on, :arm,
        :declaration_id, :declaration_version,
        CAST(:capability_versions AS jsonb), CAST(:thresholds AS jsonb), :as_of,
        :payload_hash,
        :days_since_last_sale, :days_of_cover
    )
    ON CONFLICT DO NOTHING
    """
)

# ORDER BY recorded_at, event_id — order is part of the reader protocol's contract, and
# recorded_at alone is not total (two events can share a timestamp). event_id breaks the tie
# deterministically, the same reasoning as the collapse helper's uuidv7 terminator.
_SELECT = text(
    """
    SELECT event_id, recorded_at, supersedes,
           target, verb, quantity_at_stake, expires_on, arm,
           declaration_id, declaration_version, capability_versions, thresholds, as_of,
           days_since_last_sale, days_of_cover
    FROM synapse.actions
    ORDER BY recorded_at, event_id
    LIMIT :limit
    """
)

# A runaway guard that RAISES rather than clamps, for the same reason daily_series does: a
# truncated log reads as a shorter HISTORY rather than as a partial answer, and an attribution
# study over a silently-shortened log is wrong rather than incomplete.
_MAX_ROWS = 20_000


def payload_hash(action: Action) -> str:
    """sha256 over the parts of an action that may legitimately differ under one natural key.

    THE NATURAL KEY IS NOT ENOUGH ON ITS OWN. Uniqueness on
    ``(declaration_id, declaration_version, verb, as_of, target)`` alone would suppress a
    CORRECTION — a changed quantity, or a changed arm after a deliberate salt change — exactly
    as uniqueness on canonical's D33 dedup key alone would have silently dropped source
    corrections. This hash is the fifth component that splits a retry from a correction.

    WHAT IS COVERED, and why each: ``quantity_at_stake`` and ``expires_on``, because the
    underlying data can move between runs; ``arm``, because a salt change is a NEW experiment
    and must land rather than be swallowed; ``capability_versions`` and ``thresholds``, because
    an action computed under different inputs is a different action even when it looks the same.

    WHAT IS NOT: the natural key itself. Including it would be redundant — the index already
    carries those columns — and it would blur which of the two reasons two rows differ.

    ``sort_keys`` with a fixed separator, the same discipline as the streaming consumer's
    ``canonical_row_hash``. An unsorted mapping would hash differently between runs and every
    retry would land as a correction — the exact failure this mechanism exists to prevent,
    arriving through the back door.

    ``format(..., "f")`` rather than ``str()`` on the Decimal: ``str(Decimal("1E+2"))`` is
    ``"1E+2"`` while ``format`` gives ``"100"``, so two equal quantities would otherwise hash
    differently depending on how they were constructed.
    """
    material = {
        "quantity_at_stake": None
        if action.quantity_at_stake is None
        else format(action.quantity_at_stake, "f"),
        "expires_on": action.expires_on.isoformat(),
        "arm": action.arm.value,
        "capability_versions": dict(sorted(action.provenance.capability_versions.items())),
        "thresholds": dict(sorted(action.provenance.thresholds.items())),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json(mapping: Mapping[str, Any]) -> str:
    """Canonical JSON for a bind parameter. Sorted keys, so jsonb equality is reachable."""
    return json.dumps(dict(mapping), sort_keys=True, separators=(",", ":"))


def parameters(event: ActionEvent) -> dict[str, Any]:
    """Flatten one event into bind parameters. Pure, so the mapping is testable with no database."""
    action = event.action
    return {
        "event_id": str(event.event_id),
        "recorded_at": event.recorded_at,
        "supersedes": None if event.supersedes is None else str(event.supersedes),
        "target": _json(action.target),
        "verb": action.verb.value,
        "quantity_at_stake": action.quantity_at_stake,
        "expires_on": action.expires_on,
        "arm": action.arm.value,
        "declaration_id": action.provenance.declaration_id,
        "declaration_version": action.provenance.declaration_version,
        "capability_versions": _json(action.provenance.capability_versions),
        "thresholds": _json(action.provenance.thresholds),
        "as_of": action.provenance.as_of,
        "payload_hash": payload_hash(action),
        # OBSERVATIONS, and deliberately NOT in payload_hash's material — see payload_hash().
        # Two rows differing only here are the SAME action seen twice, so the second is
        # suppressed by uq_actions_idempotency and the first observation is what persists.
        "days_since_last_sale": action.days_since_last_sale,
        "days_of_cover": action.days_of_cover,
    }


def project(row: Mapping[str, Any]) -> ActionEvent:
    """Rebuild one event from a row. Pure, and it VALIDATES on the way through.

    Every dataclass ``__post_init__`` runs here — the arm vocabulary, the non-empty target, the
    expiry ordering, the non-empty capability versions. So a row that somehow violated the
    table's CHECK constraints fails LOUDLY on read rather than being handed to a consumer as a
    plausible action. Same reasoning as ``current_state`` validating every row through the
    canonical model rather than trusting the schema.
    """
    return ActionEvent(
        event_id=_as_uuid(row["event_id"]),
        recorded_at=_as_datetime(row["recorded_at"]),
        supersedes=None if row["supersedes"] is None else _as_uuid(row["supersedes"]),
        action=Action(
            target=dict(row["target"]),
            verb=Verb(row["verb"]),
            quantity_at_stake=_as_decimal(row["quantity_at_stake"]),
            expires_on=_as_date(row["expires_on"]),
            arm=Arm(row["arm"]),
            # Read back so a round-trip is lossless. NULL for any row written before migration
            # 0004, and for the analysis that does not produce that measure.
            days_since_last_sale=row["days_since_last_sale"],
            days_of_cover=_as_decimal(row["days_of_cover"]),
            provenance=Provenance(
                declaration_id=str(row["declaration_id"]),
                declaration_version=str(row["declaration_version"]),
                capability_versions=dict(row["capability_versions"]),
                thresholds=dict(row["thresholds"]),
                as_of=_as_date(row["as_of"]),
            ),
        ),
    )


def _as_uuid(value: object) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _as_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"recorded_at came back as {type(value).__name__}, expected datetime")
    return value


def _as_date(value: object) -> date:
    """A DATE, and specifically not a datetime — ``datetime`` subclasses ``date``."""
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError(f"expected a plain date, got {type(value).__name__}")
    return value


def _as_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        raise ValueError(
            f"quantity_at_stake came back as {type(value).__name__}, expected Decimal over "
            "NUMERIC(14,3); a float here is a driver change on a figure someone reconciles"
        )
    return value


class PostgresActionAppender:
    """Writes events. Has NO ``events()`` — see the module docstring.

    Takes an engine by INJECTION and constructs none; this class reads no DSN from the
    environment, the same posture as every resolver. The engine should belong to
    ``synapse_writer``, whose grants make an accidental UPDATE impossible rather than unlikely.
    """

    def __init__(self, engine: AsyncEngine, tenant_id: UUID) -> None:
        # THE TENANT IS FIXED AT CONSTRUCTION, not passed per append. synapse.actions carries
        # two-GUC RLS whose WITH CHECK pins every inserted row to the session's tenant, so an
        # appender taking a tenant per call would either open a session per row or attempt a
        # cross-tenant insert the policy refuses. `resolve_declaration` is already tenant-scoped,
        # so nothing upstream wants otherwise.
        self._engine = engine
        self._tenant_id = tenant_id

    async def append(self, event: ActionEvent) -> bool:
        """Record one event. Returns whether it LANDED — ``False`` means it was suppressed.

        Inside ``rls_session`` so both GUCs are set: the policy's WITH CHECK compares the session
        tenant against the GENERATED ``tenant_id``, derived from ``target``. An event whose
        target names a different tenant is refused BY THE DATABASE rather than by a check here,
        which is the stronger place for it.

        THE RETURN VALUE ARRIVED IN SLICE 6 and this docstring used to say the opposite —
        "cannot report suppression". That was true of a caller who only wanted the row written,
        and false as soon as ``synapse.run`` needed to record how many actions a run actually
        added. ``rowcount`` after ``ON CONFLICT DO NOTHING`` is 1 for an insert and 0 for a
        suppression, so the information was always there and simply thrown away.

        It is a real distinction rather than bookkeeping: a second attempt at one slot proposing
        four actions and appending ZERO is the idempotency working exactly as designed, and
        without this a run row could only claim it had appended four.
        """
        async with rls_session(self._engine, self._tenant_id) as conn:
            result = await conn.execute(_INSERT, parameters(event))
        return bool(result.rowcount)


class PostgresActionReader:
    """Reads events back. Has NO ``append()``.

    The engine should belong to ``synapse_reader``, which holds SELECT on ``synapse.actions``
    and no INSERT anywhere. Scoped to one tenant by RLS, like everything else here.
    """

    def __init__(self, engine: AsyncEngine, tenant_id: UUID) -> None:
        self._engine = engine
        self._tenant_id = tenant_id

    async def events(self) -> Sequence[ActionEvent]:
        """Every event for this tenant, in append order, validated on the way out.

        Raises ``ResultTooLargeError`` rather than truncating: a shortened log reads as a shorter
        HISTORY, and an attribution study over one is wrong rather than incomplete. Pagination
        (DIS's D124 keyset pattern) is the answer when a real consumer needs more.
        """
        async with rls_session(self._engine, self._tenant_id) as conn:
            rows = (await conn.execute(_SELECT, {"limit": _MAX_ROWS + 1})).mappings().all()

        if len(rows) > _MAX_ROWS:
            raise ResultTooLargeError(
                f"the action log holds more than {_MAX_ROWS} events for tenant "
                f"{self._tenant_id}; it was NOT truncated, because a shortened log reads as a "
                "shorter history. Paginate (D124) rather than raising the limit"
            )
        return [project(dict(row)) for row in rows]


__all__ = [
    "PostgresActionAppender",
    "PostgresActionReader",
    "parameters",
    "payload_hash",
    "project",
]
