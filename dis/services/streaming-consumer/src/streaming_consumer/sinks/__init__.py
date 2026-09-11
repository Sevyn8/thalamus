"""Sinks: the canonical dual-write, the fire-and-forget audit emitter, and quarantine.

``dlq.py`` deliberately does not exist: no backpressure/DLQ path exists on this
consumer yet.
"""

from __future__ import annotations
