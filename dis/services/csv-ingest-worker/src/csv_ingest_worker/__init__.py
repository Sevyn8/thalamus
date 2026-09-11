"""csv-ingest-worker — the CSV upload ingest worker.

Triggered by the ``csv.received`` event dis-ui-server publishes once a tenant's
signed-PUT upload is confirmed saved in GCS. The worker TRUSTS the event: it
reads the resolved internal identity (UUID ``tenant_id``/``store_id``) and the
``trace_id`` off the envelope, calls no Identity Service, and mints no ``trace_id``.

Per event: cross-check the GCS path against the event identity, DuckDB
structural preflight, the dis-pii fail-loud gate, one metadata-only bronze row
via dis-rls, then — only on preflight success — the frozen ``ingress.ready``
publish (write-then-conditionally-publish). Idempotent: same content hash +
upload session + tenant within 24h returns the prior ``trace_id``
(resume-and-mark semantics).
"""

from __future__ import annotations
