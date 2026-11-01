"""The LLM's playlist proposal.

Sizes are not constrained here: the guard in `src/conversation/criteria.py` clamps them in Python,
whatever the LLM returns.
"""

from pydantic import BaseModel, Field

from src.models.conversation.track_suggestion import TrackSuggestion


class PlaylistDraft(BaseModel):
    """The LLM's own playlist proposal (title/artist pairs, never Spotify data)."""

    title: str = Field(description="Short playlist title, in the user's language.")
    description: str = Field(description="One-sentence playlist description.")
    target_size: int = Field(description="Number of tracks the user asked for.")
    tracks: list[TrackSuggestion] = Field(description="Candidate tracks, in order.")
