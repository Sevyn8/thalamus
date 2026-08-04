"""The THREE outcomes of asking for an ANALYSIS. Pure types; no DB, no SQL.

One level up from ``synapse.core.resolution``, and the same lesson applies at both levels: a
declaration with two requirements has a PRODUCT of per-capability outcomes, and collapsing that
product to a single reason repeats slice 1's original mistake one layer higher. Slice 1's was
"unavailable" meaning both "no such capability" and "this tenant is 48 days short". The
declaration-level version would be "dead_stock is unavailable" meaning either "last_sale_at does
not exist" or "current_state exists and this tenant has no rows" — states an operator fixes
differently.

So ``DeclarationBlocked`` carries a MAPPING of capability id to the underlying ``Resolution``,
not a reason. Every requirement is evaluated, so someone fixing one is told about the other.

A DECLARATION IS SATISFIED ONLY IF EVERY REQUIREMENT IS, and that is structural rather than a
convention worth arguing about:

- There is no ``optional`` flag on ``CapabilityRequirement``, and adding one would need a
  semantics for what the analysis computes without that input. Nothing has one.
- ``AnalysisDeclaration.__post_init__`` already refuses zero requirements as "no inputs".
- For ``dead_stock`` the partial cases are not partial answers, they are WRONG ones: without
  ``current_state`` there is no universe, so no absence is derivable at all; without
  ``last_sale_at`` every SKU looks never-sold and the whole catalogue reads as dead. Same shape
  as the truncation argument in ``ResultTooLargeError`` — refuse rather than half-answer.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from synapse.core.analysis import AnalysisDeclaration
from synapse.core.resolution import Resolution, Satisfied

# A bound, ready-to-call fetch for one required capability. Loosely typed for the same reason
# ``resolve()`` returns ``Resolution[object]``: a STRING-KEYED mapping cannot carry a row type,
# and a cast would be a lie in the signature. The evaluator knows which rows it asked for.
type Fetch = Callable[[], Awaitable[Sequence[object]]]


class DeclarationStatus(StrEnum):
    """The tag, for rendering and logs. The TYPE is what callers branch on."""

    SATISFIED = "satisfied"
    BLOCKED = "blocked"
    UNDECLARED = "undeclared"


@dataclass(frozen=True)
class DeclarationSatisfied:
    """Every requirement resolved. Carries one bound fetch per capability id.

    THE SAME CHECK-THEN-FETCH POSTURE AS ``Satisfied``, and the same reason: an operator console
    asking "could dead_stock run for this tenant" must not pay for two full reads to find out.
    Nothing is fetched until a caller awaits.

    Keyed by capability id rather than being a tuple, so a consumer names what it wants instead
    of relying on requirement order. Order would be a second thing to keep in agreement with the
    declaration.

    IT CARRIES THE RESOLUTIONS, NOT JUST THE FETCHES, and provenance is what forced the change.
    Slice 3 kept only the bound fetches and discarded the per-capability ``Satisfied`` objects —
    which hold the DESCRIPTORS, and therefore the capability VERSIONS. So "which capability
    resolutions produced this action" was unrecordable, and a provenance record missing capability
    versions is exactly the silent omission the provenance rule forbids.

    ``fetches`` is now DERIVED rather than stored, so there is no second source of truth to drift:
    a fetch IS ``resolutions[capability_id].fetch``.
    """

    status: ClassVar[DeclarationStatus] = DeclarationStatus.SATISFIED

    declaration: AnalysisDeclaration
    resolutions: Mapping[str, Satisfied[object]]

    def __post_init__(self) -> None:
        required = {requirement.capability_id for requirement in self.declaration.requires}
        if set(self.resolutions) != required:
            raise ValueError(
                f"analysis {self.declaration.id!r} requires {sorted(required)} but carries "
                f"resolutions for {sorted(self.resolutions)}; satisfied means EVERY requirement, "
                "and a missing one here would let a consumer compute over one input"
            )

    @property
    def fetches(self) -> Mapping[str, Fetch]:
        """The bound fetch per capability. Derived, so it cannot disagree with the resolutions."""
        return {capability_id: resolution.fetch for capability_id, resolution in self.resolutions.items()}

    @property
    def capability_versions(self) -> Mapping[str, str]:
        """Capability id -> descriptor version, for ``Provenance``.

        THE REASON THIS CLASS CARRIES RESOLUTIONS AT ALL. An attribution study comparing actions
        across a capability version change is averaging two systems, and cannot know it without
        this.
        """
        return {
            capability_id: resolution.descriptor.version
            for capability_id, resolution in self.resolutions.items()
        }


@dataclass(frozen=True)
class DeclarationBlocked:
    """At least one requirement did not resolve. Carries the per-capability outcome for each.

    THE MAPPING IS THE WHOLE POINT. Both of these are ``DeclarationBlocked`` and they are not
    the same situation:

        {"last_sale_at": Unregistered(...)}          -> the capability does not exist
        {"daily_series": PreconditionUnmet(...)}     -> it exists; this tenant is short, by N

    Flattening them to a string loses exactly what an operator needs. And a declaration blocked
    on TWO requirements reports both, because someone about to fix one wants to know the other
    is also waiting.
    """

    status: ClassVar[DeclarationStatus] = DeclarationStatus.BLOCKED

    declaration: AnalysisDeclaration
    blocked: Mapping[str, Resolution[object]]

    def __post_init__(self) -> None:
        if not self.blocked:
            raise ValueError(
                f"DeclarationBlocked for {self.declaration.id!r} names no blocked requirement; "
                "that is a DeclarationSatisfied in disguise"
            )
        satisfied = sorted(k for k, v in self.blocked.items() if isinstance(v, Satisfied))
        if satisfied:
            raise ValueError(
                f"DeclarationBlocked for {self.declaration.id!r} carries SATISFIED outcomes for "
                f"{satisfied}. Unlike the per-capability layer — where 'satisfied' depends on a "
                "policy this type cannot see — Satisfied is unambiguous here, so the engine's "
                "filter can be checked rather than trusted"
            )
        unknown = sorted(set(self.blocked) - {r.capability_id for r in self.declaration.requires})
        if unknown:
            raise ValueError(
                f"DeclarationBlocked for {self.declaration.id!r} names {unknown}, which it does not require"
            )


@dataclass(frozen=True)
class DeclarationUndeclared:
    """No analysis is declared under this id. The analogue of ``Unregistered``.

    No ``declined_reason`` counterpart, and its absence is a claim rather than an oversight:
    ``_DECLINED`` exists because a CAPABILITY can be known-impossible for a verified reason
    (``lead_time_distribution`` has no input data). Nothing analogous exists for analyses — an
    analysis is a rule someone chose to write, so the only reason one is absent is that nobody
    wrote it. Inventing a declined-analyses mapping before a single case exists would be the
    guessing this project's contracts keep refusing.
    """

    status: ClassVar[DeclarationStatus] = DeclarationStatus.UNDECLARED

    analysis_id: str


type DeclarationResolution = DeclarationSatisfied | DeclarationBlocked | DeclarationUndeclared

__all__ = [
    "DeclarationBlocked",
    "DeclarationResolution",
    "DeclarationSatisfied",
    "DeclarationStatus",
    "DeclarationUndeclared",
    "Fetch",
]
