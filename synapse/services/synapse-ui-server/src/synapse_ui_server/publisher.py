"""The concrete Pub/Sub publisher, and why it lives here rather than in Axon.

``axon.envelope`` holds the ``SendRequested`` shape and a ``Publisher`` Protocol and imports no
Pub/Sub. This module holds the one implementation that does, and ``google-cloud-pubsub`` is
declared in THIS service's dependencies. The split is a dependency decision: ``thalamus-axon`` is
a library imported by this service, and if the client lived there every consumer of Axon would
grow a gRPC stack whether it publishes or not. Same shape, same reason, as dis-ui-server's
``publisher.py``.

EMULATOR OR AMBIENT, DECIDED BY THE CLIENT ITSELF. ``pubsub_v1.PublisherClient`` honours
``PUBSUB_EMULATOR_HOST`` natively: set means the local emulator, unset means real Pub/Sub through
ambient application-default credentials. Construction is identical either way and is offline, the
channel connects on first publish, so startup stays lazy and matches the engine posture.
"""

from __future__ import annotations

import os

from dis_core.logging import get_logger

__all__ = ["PubsubPublisher"]

_log = get_logger("synapse-ui-server")


class PubsubPublisher:
    """Publish bytes to a topic; return the server-assigned message id.

    SATISFIES axon.Publisher STRUCTURALLY, never by inheriting it. The Protocol is
    runtime_checkable and a test asserts this class satisfies it, so a Protocol change cannot
    leave the fakes and the real client disagreeing about the contract.
    """

    def __init__(self, *, project_id: str) -> None:
        mode = "emulator" if os.environ.get("PUBSUB_EMULATOR_HOST") else "ambient"
        _log.info("pubsub publisher constructed", extra={"pubsub_mode": mode})
        from google.cloud import pubsub_v1  # lazy: only the runtime path needs it

        self._project_id = project_id
        self._client = pubsub_v1.PublisherClient()

    def publish(self, topic_name: str, data: bytes) -> str:
        topic_path = self._client.topic_path(self._project_id, topic_name)
        future = self._client.publish(topic_path, data)
        message_id: str = future.result()
        return message_id
