"""One chat turn: rate limit, expiry, intent gate, LLM reply, Spotify resolution, one save.

A failed turn writes nothing, so a retry does not duplicate the user message. The LLM gets
only the stored messages and its own draft; resolved Spotify tracks stay out of the prompt.
"""

import streamlit as st

from src import chain, intent_gate, rate_limiter, session_store
from src.models.conversation.assistant_turn import AssistantTurn
from src.models.conversation.playlist_draft import PlaylistDraft
from src.models.session.chat_message import ChatMessage
from src.models.session.pending_action import PendingAction
from src.models.session.session_state import SessionState
from src.models.spotify.resolved_track import ResolvedTrack
from src.spotify import resolver
from src.spotify.errors import SpotifyError
from src.ui import errors, styles
from src.ui import state as ui_state

ASSISTANT_AVATAR = ":material/graphic_eq:"  # Avatar of assistant and notice bubbles
SKELETON_ROWS = 5  # Placeholder rows shown while tracks are resolved


def _reply(text: str, state: SessionState) -> AssistantTurn | None:
    """Gate the message, then call the LLM behind the equalizer; errors are shown, not raised.

    A message the intent gate blocks gets a fixed off-topic turn and never reaches Gemini.

    Args:
        text: The new user message.
        state: The cached session (history before the new message, current draft).

    Returns:
        The guarded turn, or None when the call failed.
    """
    indicator = st.empty()
    indicator.markdown(styles.equalizer_html(), unsafe_allow_html=True)
    try:
        gated = intent_gate.gate_turn(text, state.messages)
        return gated or chain.run_turn(text, state.messages, state.draft)
    except Exception as exc:  # Every failure becomes a mapped, logged message
        st.error(errors.assistant_error_message(exc))
        return None
    finally:
        indicator.empty()


def _resolve(draft: PlaylistDraft) -> list[ResolvedTrack] | None:
    """Resolve the draft on Spotify behind skeleton rows and an n/N progress line.

    Args:
        draft: The LLM's guarded draft.

    Returns:
        The resolved tracks, or None when Spotify failed.
    """
    status, skeleton = st.empty(), st.empty()
    rows = min(draft.target_size, SKELETON_ROWS)
    skeleton.markdown(styles.skeleton_rows_html(rows), unsafe_allow_html=True)

    def progress(done: int, total: int) -> None:
        """Show resolution progress.

        Args:
            done: Suggestions searched so far.
            total: Suggestions to search.
        """
        status.caption(f"Finding tracks on Spotify… {done}/{total}")

    progress(0, len(draft.tracks))
    try:
        return resolver.resolve_tracks(draft.tracks, draft.target_size, on_progress=progress)
    except SpotifyError as exc:
        st.error(errors.spotify_error_message(exc))
        return None
    finally:
        status.empty()
        skeleton.empty()


def _changes(
    state: SessionState, turn: AssistantTurn, tracks: list[ResolvedTrack] | None
) -> dict[str, object]:
    """Session changes of a turn: a new draft binds its card and buttons to the reply.

    Args:
        state: The cached session before the turn.
        turn: The guarded LLM turn.
        tracks: Resolved tracks of a new draft, None for other intents.

    Returns:
        Keyword changes for `save_turn` (indexes on the untrimmed message list).
    """
    if turn.playlist is None or tracks is None:
        return {"pending_action": None}  # A new message always dismisses stale buttons
    index = len(state.messages) + 1  # The assistant reply, right after the user message
    kind = "confirm_create" if state.mode == "spotify" else "login_to_save"
    found = any(t.found for t in tracks)  # No button for a playlist with nothing to save
    action = PendingAction.model_validate({"kind": kind, "message_index": index}) if found else None
    return {
        "draft": turn.playlist,
        "draft_message_index": index,
        "resolved_tracks": tracks,
        "created_playlist": None,
        "pending_action": action,
    }


def handle_user_message(text: str) -> None:
    """Process a chat message end to end, then rerun to show the saved conversation.

    Args:
        text: The message typed by the user.
    """
    if rate_limiter.is_rate_limited(rate_limiter.get_client_ip()):
        st.warning(errors.RATE_LIMITED)
        return
    state = ui_state.active()
    if state is None:  # Expired just now: the rerun shows the expired screen
        st.rerun()
        return
    with st.chat_message("user"):
        st.markdown(text)
    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        turn = _reply(text, state)
        if turn is None:
            return
        st.markdown(turn.message)
        tracks = _resolve(turn.playlist) if turn.playlist is not None else None
        if turn.playlist is not None and tracks is None:
            return
    reply = ChatMessage(role="assistant", content=turn.message)
    user = ChatMessage(role="user", content=text)
    changes = _changes(state, turn, tracks)
    if ui_state.persist(lambda: session_store.save_turn(state, [user, reply], **changes)):
        st.rerun()
