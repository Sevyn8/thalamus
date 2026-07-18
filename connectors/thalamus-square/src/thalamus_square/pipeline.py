"""Wire the SquareAdapter into the shared ConnectorPipeline.

Reuses the csv-ingest-worker runtime seams (the GCS client, the ingress.ready publisher)
and the RLS engine, exactly as the CSV worker's main does, so a Square connector deploys
with the same data-plane wiring. ``pii_backend=None`` keeps the gate fail-loud (v1, D40).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from csv_ingest_worker.publisher import PubsubPublisher
from dis_audit import AuditBackend, select_writer
from dis_rls import create_rls_engine
from dis_storage import StorageClient
from thalamus_connector_sdk import ConnectorAudit, ConnectorPipeline, SdkConfig
from thalamus_square.adapter import SquareAdapter
from thalamus_square.auth import EnvTokenStore, TokenStore
from thalamus_square.config import SERVICE_NAME, SquareConfig
from thalamus_square.puller import SquareApi, SquarePuller


def build_engine(sdk_config: SdkConfig) -> AsyncEngine:
    """The RLS-aware engine (inherits the current_database() target guard)."""
    return create_rls_engine(sdk_config.postgres_url)


def build_square_pipeline(
    sdk_config: SdkConfig,
    square_config: SquareConfig,
    *,
    engine: AsyncEngine,
    token_store: TokenStore | None = None,
    api: SquareApi | None = None,
) -> ConnectorPipeline:
    """Construct the wired ConnectorPipeline for the Square connector.

    ``engine`` is caller-owned (so main can dispose it). ``token_store`` / ``api`` default
    to the env token store and the httpx puller; tests inject fakes.
    """
    resolved_api: SquareApi = api or SquarePuller(
        base_url=square_config.base_url, api_version=square_config.api_version
    )
    resolved_store: TokenStore = token_store or EnvTokenStore()
    adapter = SquareAdapter(api=resolved_api, token_store=resolved_store)
    return ConnectorPipeline(
        engine=engine,
        storage=StorageClient(bucket=sdk_config.bronze_bucket),
        publisher=PubsubPublisher(project_id=sdk_config.pubsub_project_id),
        audit=ConnectorAudit(select_writer(AuditBackend.POSTGRES, engine=engine), service_name=SERVICE_NAME),
        bronze_bucket=sdk_config.bronze_bucket,
        adapter=adapter,
        connector_name="square",
        pii_backend=None,  # v1.0: NO real backend exists; the gate fails loud (D40)
    )
