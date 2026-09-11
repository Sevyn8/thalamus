"""Internal data-plane identifier vocabulary.

The DIS data plane keys every canonical, RLS, audit, and storage path by the
**internal 128-bit UUID** that ``identity_mirror`` and ``canonical.*`` use as
primary keys. These aliases name that vocabulary in one place so the data-plane
libs (``dis-rls``, ``dis-pii``, ``dis-storage``, ``dis-audit``) and
``dis-canonical`` share one definition instead of redefining it each.

The identity contract (``dis_core.identity.models``) carries the same internal
UUIDs on its response models; no external string-alias form of these identifiers
exists. Import the UUID forms from here for anything touching the
DB/RLS/canonical.
"""

from __future__ import annotations

from uuid import UUID

# Internal UUID keys (UUIDv7). NOT the external t_*/s_* contract strings.
TenantId = UUID
StoreId = UUID
TraceId = UUID

# config.source_mappings.mapping_version_id is BIGINT.
MappingVersionId = int
