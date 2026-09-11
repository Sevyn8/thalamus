"""Wire the SquareAdapter into the shared ConnectorPipeline.

Reuses the csv-ingest-worker runtime seams (the GCS client, the ingress.ready publisher)
and the RLS engine, exactly as the CSV worker's main does, so a Square connector deploys
with the same data-plane wiring. ``pii_backend=None`` keeps the gate fail-loud
(v1: no real PII backend exists yet).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncEngine

from csv_ingest_worker.publisher import PubsubPublisher
from dis_audit import AuditBackend, select_writer
from dis_rls import create_rls_engine
from dis_storage import StorageClient
from thalamus_connector_sdk import ConnectorAudit, ConnectorPipeline, SdkConfig
from thalamus_square.adapter import SquareAdapter
from thalamus_square.auth import TokenStore, VaultTokenStore
from thalamus_square.config import SERVICE_NAME, SquareConfig, SquareOAuthConfig
from thalamus_square.puller import SquareApi, SquarePuller
from thalamus_square_oauth import (
    SQUARE_READ_SCOPES,
    GoogleSecretBackend,
    SquareOAuthClient,
    SquareTokenVault,
)


def build_engine(sdk_config: SdkConfig) -> AsyncEngine:
    """The RLS-aware engine (inherits the current_database() target guard)."""
    return create_rls_engine(sdk_config.postgres_url)


def _default_token_store() -> TokenStore:
    """The S2 production token store: the Secret Manager-backed OAuth vault.

    Built only when no ``token_store`` is injected (tests / dev_transport inject a fake), so
    resolving the OAuth config from env happens on the real production path only. The GCP
    client is credential-lazy, so construction does no I/O; the OAuth config IS required
    (raises ``ConnectorConfigError`` if the env is absent) since production genuinely needs it.
    """
    oauth_config = SquareOAuthConfig.from_env()
    vault = SquareTokenVault(GoogleSecretBackend(project_id=oauth_config.secrets_project_id))
    client = SquareOAuthClient(
        base_url=oauth_config.oauth_base_url,
        client_id=oauth_config.client_id,
        client_secret=oauth_config.client_secret,
        redirect_uri="",  # unused on the refresh-only connector path
        scopes=SQUARE_READ_SCOPES,
        environment=oauth_config.environment,
    )
    return VaultTokenStore(
        vault=vault,
        client=client,
        refresh_skew=timedelta(seconds=oauth_config.refresh_skew_seconds),
    )


def build_square_pipeline(
    sdk_config: SdkConfig,
    square_config: SquareConfig,
    *,
    engine: AsyncEngine,
    token_store: TokenStore | None = None,
    api: SquareApi | None = None,
) -> ConnectorPipeline:
    """Construct the wired ConnectorPipeline for the Square connector.

    ``engine`` is caller-owned (so main can dispose it). ``api`` defaults to the httpx
    puller; ``token_store`` defaults to the Secret Manager OAuth vault (:func:
    `_default_token_store`). Tests and dev_transport inject fakes for both.
    """
    resolved_api: SquareApi = api or SquarePuller(
        base_url=square_config.base_url, api_version=square_config.api_version
    )
    resolved_store: TokenStore = token_store or _default_token_store()
    adapter = SquareAdapter(api=resolved_api, token_store=resolved_store)
    return ConnectorPipeline(
        engine=engine,
        storage=StorageClient(bucket=sdk_config.bronze_bucket),
        publisher=PubsubPublisher(project_id=sdk_config.pubsub_project_id),
        audit=ConnectorAudit(select_writer(AuditBackend.POSTGRES, engine=engine), service_name=SERVICE_NAME),
        bronze_bucket=sdk_config.bronze_bucket,
        adapter=adapter,
        connector_name="square",
        pii_backend=None,  # v1.0: NO real backend exists; the gate fails loud
    )
