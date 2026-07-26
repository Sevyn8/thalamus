"""The Square read scopes DIS requests, one source of truth for both consumers.

The BFF requests these on the authorize URL; the connector stamps them onto stored token
sets. Keeping the tuple here means the connect grant and the recorded scopes cannot drift.
"""

from __future__ import annotations

SQUARE_READ_SCOPES: tuple[str, ...] = (
    "MERCHANT_PROFILE_READ",
    "ITEMS_READ",
    "INVENTORY_READ",
    "ORDERS_READ",
)
