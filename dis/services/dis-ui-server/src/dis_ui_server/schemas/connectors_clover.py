"""Wire shapes for the Clover OAuth connect endpoints (C3).

Duplicated from ``connectors_square`` rather than generalised (D5): the two vendors' OAuth
genuinely differs, and one shared shape would have to paper over that. The visible
difference is right here - ``OAuthCompleteRequest`` carries a ``merchant_id``, because
Clover's token response does NOT contain one and the SPA must pass back what the callback
gave it. Square's merchant id comes out of the exchange.

No token or secret ever appears on the wire.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AuthorizeUrlResponse(BaseModel):
    """The merchant-facing Clover authorization URL plus the signed state to echo back."""

    authorize_url: str
    state: str


class OAuthCompleteRequest(BaseModel):
    """The SPA's exchange request: the code + state + merchant Clover returned to launch.

    ``merchant_id`` is required because Clover reports it on the CALLBACK QUERY STRING and
    not in the token response, so the server cannot recover it from the exchange. It is
    stored on the token record, which is what makes every later ``/v3/merchants/{mId}/...``
    call possible.
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    state: str = Field(min_length=1)
    merchant_id: str = Field(min_length=1, max_length=64)
    # Clover also returns an employee_id on the callback. Optional: it identifies WHO
    # authorised, which is useful provenance on the stored record but is not needed to call
    # the API, so a missing one must never block a connect.
    employee_id: str | None = None


class OAuthCompleteResponse(BaseModel):
    """The minimal success signal the frontend renders."""

    connector: str
    status: str
    source_id: str
    merchant_id: str
