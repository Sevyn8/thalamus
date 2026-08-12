"""The readiness heartbeat, and the /healthz surface Cloud Run probes.

WHY A HEARTBEAT AND NOT A BARE 200. A process can be alive and its loop dead: an unhandled
condition inside the pull, a hung gRPC call, a thread that stopped. A handler that returns 200
because the web server is up would report that as healthy for as long as the container runs, and
the queue would grow with nothing saying so. The loop beats once per pass; the handler reports
stale if the last beat is older than the window.

Copied in shape from streaming-consumer's health.py and csv-ingest-worker's, which are already
two copies of this. A third is the point at which it should move to dis-core, and that is a
separate change: promoting it means a new dependency edge from Axon to a DIS lib for one class,
and this slice is not the place to argue it. Recorded so the next person has the count.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

__all__ = ["Heartbeat"]

# Generous against the loop's own cadence. A pass that finds an empty subscription blocks on the
# pull for its client deadline and then sleeps, so a healthy idle loop beats every few seconds.
# 60s is well past that and well short of a Cloud Run probe budget, so a stale reading means the
# loop stopped rather than that it was briefly busy.
_STALE_AFTER_SECONDS = 60.0


@dataclass
class Heartbeat:
    """Last time the loop completed a pass. Monotonic, so a clock change cannot fake liveness."""

    _last: float = field(default_factory=time.monotonic)

    def beat(self) -> None:
        self._last = time.monotonic()

    @property
    def age_seconds(self) -> float:
        return time.monotonic() - self._last

    @property
    def is_fresh(self) -> bool:
        return self.age_seconds < _STALE_AFTER_SECONDS
