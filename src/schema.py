"""Pydantic v2 models shared by the Spotify, conversation and session layers.

The conversation models are passed to `with_structured_output`, so their field descriptions
are short instructions for the LLM. Sizes are not constrained here: the guard in
`src/criteria.py` clamps them in Python, whatever the LLM returns.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

# ── Spotify ───────────────────────────────────────────────────────────────────


class TrackSuggestion(BaseModel):
    """A track proposed by the LLM; the resolver's input."""

    title: str = Field(description="Track title.")
    artist: str = Field(description="Main artist.")
    album: str | None = Field(default=None, description="Album, if known.")
    year: int | None = Field(default=None, description="Release year, if known.")


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


# ── Conversation ──────────────────────────────────────────────────────────────


class PlaylistCriteria(BaseModel):
    """Everything the user asked for so far, across the whole conversation."""

    genres: list[str] = Field(default_factory=list, description="Genres, e.g. house.")
    moods: list[str] = Field(default_factory=list, description="Moods or activities.")
    years: list[str] = Field(default_factory=list, description="Years or eras, e.g. 2010s.")
    artists: list[str] = Field(default_factory=list, description="Artists mentioned.")
    albums: list[str] = Field(default_factory=list, description="Albums mentioned.")
    songs: list[str] = Field(default_factory=list, description="Songs mentioned.")
    other_constraints: list[str] = Field(
        default_factory=list, description='Other constraints, e.g. "danceable", "no remixes".'
    )


class PlaylistDraft(BaseModel):
    """The LLM's own playlist proposal (title/artist pairs, never Spotify data)."""

    title: str = Field(description="Playlist title.")
    description: str = Field(description="One-sentence playlist description.")
    target_size: int = Field(description="Number of tracks the user asked for.")
    tracks: list[TrackSuggestion] = Field(description="Candidate tracks, in order.")


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


# ── Session ───────────────────────────────────────────────────────────────────


class ChatMessage(BaseModel):
    """One chat bubble; `notice` messages are app-generated and never sent to the LLM."""

    role: Literal["user", "assistant", "notice"]
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PendingAction(BaseModel):
    """Confirmation buttons, bound to the message they render under."""

    kind: Literal["confirm_create", "login_to_save"]
    message_index: int


class CreatedPlaylist(BaseModel):
    """A playlist already created on Spotify; `items_added` lets a retry resume at add_items."""

    id: str
    url: str
    items_added: bool = False


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
