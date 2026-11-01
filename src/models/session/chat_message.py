"""One chat bubble stored in the session."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """One chat bubble; `notice` messages are app-generated and never sent to the LLM."""

    role: Literal["user", "assistant", "notice"]
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
