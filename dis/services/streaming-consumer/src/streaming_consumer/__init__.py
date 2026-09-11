"""streaming-consumer — the DIS ELT path from ``ingress.ready`` to canonical.

Consumes ``ingress.ready``, fetches the bronze chunk, loads the active mapping,
validates (pre and post), applies the four mapping sub-stages, stamps
``mapping_version_id``, and atomically dual-writes canonical (hot upsert +
event insert in ONE Cloud SQL transaction) under the event's tenant via
``dis-rls``. At-least-once delivery is absorbed by the read-time dedup posture
over ``(tenant_id, store_id, source_id, source_event_id)``, never by
transactional idempotency.
"""

from __future__ import annotations
