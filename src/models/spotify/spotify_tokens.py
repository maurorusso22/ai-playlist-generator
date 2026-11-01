"""A user's Spotify OAuth tokens."""

from datetime import datetime

from pydantic import BaseModel, Field, SecretStr


class SpotifyTokens(BaseModel):
    """A user's Spotify OAuth tokens; SecretStr masks them in repr() and logs.

    `model_dump()`/`model_dump_json()` mask the tokens too: read them with
    `get_secret_value()`. `user_id`/`display_name` are filled from `GET /me` after the exchange.
    """

    access_token: SecretStr
    refresh_token: SecretStr
    expires_at: datetime = Field(description="Access token expiry (timezone-aware UTC).")
    user_id: str | None = None
    display_name: str | None = None
