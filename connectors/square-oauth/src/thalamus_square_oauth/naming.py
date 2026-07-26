"""Secret Manager secret-id derivation for a (tenant, source) token set.

One secret per tenant/source. Secret ids are constrained to ``[A-Za-z0-9_-]`` and <=255
chars; ``source_id`` (``config.sources.source_id``, up to 128 arbitrary chars) is
sanitized to that charset, and a short hash of the RAW ``source_id`` is appended so two
source ids that sanitize to the same slug never collide onto one secret.
"""

from __future__ import annotations

import hashlib
import re
from uuid import UUID

_PREFIX = "square-oauth"
_SLUG_DISALLOWED = re.compile(r"[^A-Za-z0-9_-]")
_SLUG_MAX = 40
_HASH_LEN = 8


def secret_id_for(tenant_id: UUID, source_id: str) -> str:
    """The deterministic Secret Manager secret id for one tenant/source key.

    Shape: ``square-oauth-{tenant_uuid}-{slug}-{hash8}`` (<=99 chars for a 128-char
    source_id; well under the 255 limit). The writer (BFF) and reader (connector) both
    call this, so the name can never drift between them.
    """
    slug = _SLUG_DISALLOWED.sub("_", source_id)[:_SLUG_MAX]
    digest = hashlib.sha1(source_id.encode("utf-8")).hexdigest()[:_HASH_LEN]
    return f"{_PREFIX}-{tenant_id}-{slug}-{digest}"
