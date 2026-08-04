"""Synapse's own error base. Pure; imports nothing.

WHY NOT dis_core.errors, which the root CLAUDE.md points every DIS service at: Synapse
is a PEER of DIS, not a member of it (D1). It depends on two DIS LIBRARIES — dis-canonical
for row shapes and dis-rls for the session discipline — because duplicating either would
copy safety-critical code across planes. An error taxonomy is neither: it is the
vocabulary a plane raises in, and taking DIS's would make Synapse's failures read as DIS
failures in logs and handlers. The line stays where it already is in this project: reuse
a lib when reimplementing it would duplicate a mechanism, not to save a base class.
"""

from __future__ import annotations


class SynapseError(Exception):
    """Base for every domain error Synapse raises."""


class ResultTooLargeError(SynapseError):
    """A capability's result exceeded its runaway guard, and was NOT truncated.

    RAISED RATHER THAN CAPPED, which is the opposite of what ``current_state`` does, and
    the asymmetry is deliberate. current_state's grain is (tenant, store, sku): a clamp
    returns fewer positions, and a caller can see that it got exactly the limit.
    daily_series's grain multiplies stores by SKUs by DAYS, so a clamp silently removes
    DATES from a series — and a series with missing days does not look truncated, it
    looks like days with no sales. That is a wrong answer, not a partial one, so the
    caller is told to narrow instead.
    """
