"""A suggestion matched on the Spotify catalog."""

from pydantic import BaseModel


class ResolvedTrack(BaseModel):
    """A suggestion matched on Spotify, for display and playlist creation only.

    Never sent to the LLM. For not-found entries `name`/`artists` carry the suggestion's
    title/artist and every Spotify field is None.
    """

    spotify_id: str | None = None
    uri: str | None = None
    name: str
    artists: list[str]
    album: str | None = None
    image_url: str | None = None
    external_url: str | None = None
    duration_ms: int | None = None
    found: bool
