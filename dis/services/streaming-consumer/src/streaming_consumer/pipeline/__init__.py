"""Pipeline stages (one concern per module, code-quality rule 7).

``fetch`` → ``mapping`` (load + route) → ``validate_pre`` → engine apply (via
``mapping``) → ``validate_post`` → ``normalize`` (write-shape) → sinks. Routing
is mapping-load-time and static (one chunk targets one event model); a
dedicated per-row branching module (``branch.py``) does not exist.
"""

from __future__ import annotations
