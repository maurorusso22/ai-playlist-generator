"""One structured LLM reply, the schema passed to `with_structured_output`.

Field descriptions are short instructions for the LLM.
"""

from typing import Literal

from pydantic import BaseModel, Field

from src.models.conversation.playlist_criteria import PlaylistCriteria
from src.models.conversation.playlist_draft import PlaylistDraft


class AssistantTurn(BaseModel):
    """One structured LLM reply: intent, cumulative criteria, message and optional draft."""

    intent: Literal["clarify", "propose_playlist", "revise_playlist", "off_topic"] = Field(
        description="What this reply does."
    )
    criteria: PlaylistCriteria = Field(description="Criteria from the whole conversation.")
    message: str = Field(description="Reply to the user, in the user's language.")
    playlist: PlaylistDraft | None = Field(
        default=None, description="The draft, only for propose/revise intents."
    )
