"""Builders of canned LLM turns, drafts, resolved tracks, tokens and sessions for app tests."""

from datetime import timedelta
from typing import Any

from pydantic import SecretStr

from src.conversation.criteria import candidate_count
from src.models.conversation.assistant_turn import AssistantTurn
from src.models.conversation.playlist_criteria import PlaylistCriteria
from src.models.conversation.playlist_draft import PlaylistDraft
from src.models.conversation.track_suggestion import TrackSuggestion
from src.models.session.pending_action import PendingAction
from src.models.session.session_state import SessionState
from src.models.spotify.resolved_track import ResolvedTrack
from src.models.spotify.spotify_tokens import SpotifyTokens
from src.session import crypto
from tests.unit.session_factory import NOW, make_state


def make_tracks(count: int) -> list[ResolvedTrack]:
    """Build resolved tracks with Spotify fields on the allowlisted hosts.

    Args:
        count: Number of tracks.

    Returns:
        The tracks.
    """
    return [
        ResolvedTrack(
            spotify_id=f"id{i}",
            uri=f"spotify:track:id{i}",
            name=f"Song {i}",
            artists=[f"Artist {i}"],
            album=f"Album {i}",
            image_url=f"https://i.scdn.co/image/{i}",
            external_url=f"https://open.spotify.com/track/id{i}",
        )
        for i in range(count)
    ]


def make_draft(size: int, candidates: int | None = None) -> PlaylistDraft:
    """Build an LLM draft titled "House Hits".

    Args:
        size: Target size.
        candidates: Number of suggestions (defaults to `size`).

    Returns:
        The draft.
    """
    count = candidates or size
    tracks = [TrackSuggestion(title=f"Song {i}", artist=f"Artist {i}") for i in range(count)]
    return PlaylistDraft(
        title="House Hits", description="2010s house.", target_size=size, tracks=tracks
    )


def clarify_turn() -> AssistantTurn:
    """Build a clarification turn without a playlist.

    Returns:
        The turn.
    """
    return AssistantTurn(intent="clarify", criteria=PlaylistCriteria(), message="Which genre?")


def propose_turn(size: int) -> AssistantTurn:
    """Build a playlist proposal with over-generated candidates.

    Args:
        size: Target size.

    Returns:
        The turn.
    """
    return AssistantTurn(
        intent="propose_playlist",
        criteria=PlaylistCriteria(genres=["house"]),
        message="Here you go!",
        playlist=make_draft(size, candidate_count(size)),
    )


def make_tokens(name: str | None = "Mauro") -> SpotifyTokens:
    """Build user tokens valid for one hour after NOW.

    Args:
        name: Display name; None as returned by the code exchange.

    Returns:
        The tokens.
    """
    return SpotifyTokens(
        access_token=SecretStr("access-1"),
        refresh_token=SecretStr("refresh-1"),
        expires_at=NOW + timedelta(hours=1),
        display_name=name,
    )


def draft_state(mode: str = "spotify", tracks: int = 16, **fields: Any) -> SessionState:
    """Build a session whose last message carries a draft card and its pending action.

    Args:
        mode: "spotify" (confirm_create, with tokens) or "guest" (login_to_save).
        tracks: Resolved tracks of the draft.
        **fields: Field overrides.

    Returns:
        The session state.
    """
    kind = "confirm_create" if mode == "spotify" else "login_to_save"
    base: dict[str, Any] = {
        "mode": mode,
        "draft": make_draft(tracks),
        "draft_message_index": 1,
        "resolved_tracks": make_tracks(tracks),
        "pending_action": PendingAction.model_validate({"kind": kind, "message_index": 1}),
        "spotify_auth": crypto.encrypt_tokens(make_tokens()) if mode == "spotify" else None,
    }
    return session(messages=2, **(base | fields))


def session(messages: int = 0, **fields: Any) -> SessionState:
    """Build a session like `make_state`, with any field overridden (mode included).

    Args:
        messages: Number of alternating user/assistant messages.
        **fields: Field overrides.

    Returns:
        The session state.
    """
    state: SessionState = make_state(messages=messages).model_copy(update=fields)
    return state
