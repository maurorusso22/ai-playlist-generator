"""Snapshot of a playlist saved on Spotify, shown as a card in its chat notice."""

from pydantic import BaseModel, Field


class SavedPlaylist(BaseModel):
    """What the "saved" card shows; display only, never sent to the LLM.

    Built from the draft and its resolved tracks at save time, so no extra Spotify call is
    needed: Spotify generates its own playlist mosaic asynchronously, after the items are
    added, and it would not be ready yet.
    """

    url: str
    title: str
    description: str = ""
    track_count: int
    duration_ms: int | None = None
    owner: str | None = None
    cover_urls: list[str] = Field(default_factory=list)  # 1 cover, or 4 for a mosaic
