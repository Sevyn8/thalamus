"""Wire the CloverAdapter into the shared ConnectorPipeline.

Reuses the csv-ingest-worker runtime seams (the GCS client, the ingress.ready publisher)
and the RLS engine, exactly as the Square connector's pipeline does, so a Clover connector
deploys with the same data-plane wiring. ``pii_backend=None`` keeps the gate fail-loud
(v1, D40).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from csv_ingest_worker.publisher import PubsubPublisher
from dis_audit import AuditBackend, select_writer
from dis_rls import create_rls_engine
from dis_storage import StorageClient
from thalamus_clover.adapter import CloverAdapter, SessionStore
from thalamus_clover.config import SERVICE_NAME, CloverConfig
from thalamus_clover.oauth_config import CloverOAuthEnv
from thalamus_clover.puller import CloverApi, CloverPuller
from thalamus_clover_oauth import (
    CloverOAuthClient,
    CloverTokenStore,
    CloverTokenVault,
    GoogleSecretBackend,
)
from thalamus_connector_sdk import ConnectorAudit, ConnectorPipeline, SdkConfig


def build_engine(sdk_config: SdkConfig) -> AsyncEngine:
    """The RLS-aware engine (inherits the current_database() target guard)."""
    return create_rls_engine(sdk_config.postgres_url)


def _default_token_store(clover_config: CloverConfig) -> SessionStore:
    """The production session store: the Secret Manager-backed Clover OAuth vault.

    Built only when no ``token_store`` is injected (tests / dev_transport inject a fake), so
    resolving the OAuth config from env happens on the real production path only. The GCP
    client is credential-lazy, so construction does no I/O; the OAuth config IS required
    (raises ``ConnectorConfigError`` if the env is absent) since production genuinely needs it.

    ``client_secret`` is supplied because the store may need the RECOVERY leg (D4), which
    does send it. The refresh leg does not.
    """
    oauth_env = CloverOAuthEnv.from_env()
    vault = CloverTokenVault(GoogleSecretBackend(project_id=oauth_env.secrets_project_id))
    client = CloverOAuthClient(
        base_url=clover_config.base_url,
        client_id=oauth_env.client_id,
        client_secret=oauth_env.client_secret,
        redirect_uri="",  # unused on the refresh/recovery-only connector path
    )
    return CloverTokenStore(vault=vault, client=client, refresh_skew=oauth_env.refresh_skew)


def build_clover_pipeline(
    sdk_config: SdkConfig,
    clover_config: CloverConfig,
    *,
    engine: AsyncEngine,
    token_store: SessionStore | None = None,
    api: CloverApi | None = None,
) -> ConnectorPipeline:
    """Construct the wired ConnectorPipeline for the Clover connector.

    ``engine`` is caller-owned (so main can dispose it). ``api`` defaults to the httpx
    puller; ``token_store`` defaults to the Secret Manager OAuth vault
    (:func:`_default_token_store`). Tests and dev_transport inject fakes for both.
    """
    resolved_api: CloverApi = api or CloverPuller(base_url=clover_config.base_url)
    resolved_store: SessionStore = token_store or _default_token_store(clover_config)
    adapter = CloverAdapter(api=resolved_api, token_store=resolved_store)
    return ConnectorPipeline(
        engine=engine,
        storage=StorageClient(bucket=sdk_config.bronze_bucket),
        publisher=PubsubPublisher(project_id=sdk_config.pubsub_project_id),
        audit=ConnectorAudit(select_writer(AuditBackend.POSTGRES, engine=engine), service_name=SERVICE_NAME),
        bronze_bucket=sdk_config.bronze_bucket,
        adapter=adapter,
        connector_name="clover",
        pii_backend=None,  # v1.0: NO real backend exists; the gate fails loud (D40)
    )
