"""Tenant sending-channel configuration: the credential's name, and the vault write.

THE TENANT IS THE SENDER, NEVER SEVYN8. The WhatsApp Business account, the credential
and the approved templates belong to the tenant, and a tenant administrator enters
them here. Sevyn8 never holds or types another company's credential; superadmin sees
connection STATE and never a value.
"""

from admin_backend.channels.secret_naming import secret_id_for
from admin_backend.channels.secret_writer import (
    ChannelSecretWriter,
    ChannelSecretWriterProtocol,
    SecretWriteError,
)

__all__ = [
    "ChannelSecretWriter",
    "ChannelSecretWriterProtocol",
    "SecretWriteError",
    "secret_id_for",
]
