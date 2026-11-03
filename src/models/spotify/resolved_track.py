"""A suggestion matched on the Spotify catalog."""

from pydantic import BaseModel


class ResolvedTrack(BaseModel):
    """A suggestion matched on Spotify, for display and playlist creation only.

    Never sent to the LLM. Suggestions without a match are dropped by the resolver, so every
    instance comes from a Spotify search result.
    """

    spotify_id: str | None = None
    uri: str | None = None
    name: str
    artists: list[str]
    album: str | None = None
    image_url: str | None = None
    external_url: str | None = None
    duration_ms: int | None = None
