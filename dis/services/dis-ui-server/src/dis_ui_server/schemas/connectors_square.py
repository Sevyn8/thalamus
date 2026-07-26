"""Wire shapes for the Square OAuth connect endpoints (S2).

The ``complete`` response is the minimal signal S3's SPA reads after Square redirects back
to it and it POSTs the code+state here: a success marker plus the identifiers the UI shows.
No token or secret ever appears on the wire.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AuthorizeUrlResponse(BaseModel):
    """The seller-facing Square authorization URL plus the signed state to echo back."""

    authorize_url: str
    state: str


class OAuthCompleteRequest(BaseModel):
    """The SPA's exchange request: the code + state Square returned to the SPA callback."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    state: str = Field(min_length=1)


class OAuthCompleteResponse(BaseModel):
    """The minimal success signal the frontend renders (S3 contract)."""

    connector: str
    status: str
    source_id: str
    merchant_id: str
