"""A conversation as stored in Firestore."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.models.conversation.playlist_draft import PlaylistDraft
from src.models.session.chat_message import ChatMessage
from src.models.session.created_playlist import CreatedPlaylist
from src.models.session.pending_action import PendingAction
from src.models.spotify.resolved_track import ResolvedTrack


class SessionState(BaseModel):
    """A conversation as stored in Firestore; datetimes are timezone-aware UTC."""

    session_id: str
    created_at: datetime
    last_message_at: datetime
    expires_at: datetime
    mode: Literal["guest", "spotify"]
    messages: list[ChatMessage] = Field(default_factory=list)
    draft: PlaylistDraft | None = None
    draft_message_index: int | None = None  # Message the playlist card renders under
    resolved_tracks: list[ResolvedTrack] = Field(default_factory=list)
    pending_action: PendingAction | None = None
    created_playlist: CreatedPlaylist | None = None
    oauth_state: str | None = None
    spotify_auth: str | None = None  # Fernet blob of SpotifyTokens, never plaintext
