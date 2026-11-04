"""One chat bubble stored in the session."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.models.session.saved_playlist import SavedPlaylist


class ChatMessage(BaseModel):
    """One chat bubble; `notice` messages are app-generated and never sent to the LLM.

    A notice with `saved_playlist` is rendered as the saved-playlist card instead of `content`.
    """

    role: Literal["user", "assistant", "notice"]
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    saved_playlist: SavedPlaylist | None = None
