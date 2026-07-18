"""Environment-resolved configuration for a connector worker (WorkerConfig pattern).

Reuses the csv-ingest-worker's required env names so a connector deploys with the same
data-plane wiring:

- ``POSTGRES_URL`` - the DIS write connection (``ithina_dis_user``); reused by
  ``dis-rls`` ``create_rls_engine``, which asserts ``current_database()=='ithina_dis_db'``.
- ``PUBSUB_PROJECT_ID`` - the project for the ``ingress.ready`` publisher.
- ``GCS_BUCKET_BRONZE`` - the bronze bucket the connector writes its CSV object into.

No silent default for a required value (code-quality rule 4): a missing one raises
``ConnectorConfigError``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from thalamus_connector_sdk.errors import ConnectorConfigError

_POSTGRES_URL = "POSTGRES_URL"
_PUBSUB_PROJECT_ID = "PUBSUB_PROJECT_ID"
_GCS_BUCKET_BRONZE = "GCS_BUCKET_BRONZE"


@dataclass(frozen=True)
class SdkConfig:
    """Resolved data-plane profile shared by every connector worker."""

    postgres_url: str
    pubsub_project_id: str
    bronze_bucket: str

    @classmethod
    def from_env(cls) -> SdkConfig:
        """Resolve from the environment, raising on any missing required value."""
        postgres_url = os.environ.get(_POSTGRES_URL)
        if not postgres_url:
            raise ConnectorConfigError(
                f"{_POSTGRES_URL} is not set; cannot reach the DIS database for the bronze write"
            )
        pubsub_project_id = os.environ.get(_PUBSUB_PROJECT_ID)
        if not pubsub_project_id:
            raise ConnectorConfigError(f"{_PUBSUB_PROJECT_ID} is not set; cannot publish ingress.ready")
        bronze_bucket = os.environ.get(_GCS_BUCKET_BRONZE)
        if not bronze_bucket:
            raise ConnectorConfigError(
                f"{_GCS_BUCKET_BRONZE} is not set; cannot write the connector's bronze object"
            )
        return cls(
            postgres_url=postgres_url,
            pubsub_project_id=pubsub_project_id,
            bronze_bucket=bronze_bucket,
        )
