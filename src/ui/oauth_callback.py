"""Spotify OAuth callback (`?code&state` or `?error`), handled after the bootstrap.

The callback is a full page load, so it runs in a new Streamlit session whose bootstrap has
just restored the conversation from localStorage. It is processed once per session, the
query parameters are cleared, and a pending draft is offered for creation (FR-07).
"""

import logging

import streamlit as st

from src import crypto, session_store
from src.models.session.chat_message import ChatMessage
from src.models.session.pending_action import PendingAction
from src.models.session.session_state import SessionState
from src.models.spotify.spotify_tokens import SpotifyTokens
from src.spotify import auth
from src.spotify import client as spotify_client
from src.spotify.errors import SpotifyError, SpotifyForbiddenError
from src.ui import errors
from src.ui import state as ui_state

CALLBACK_KEY = "oauth_callback_done"  # Set once the callback of this tab has been processed

_logger = logging.getLogger(__name__)


def _notice(state: SessionState, text: str, **changes: object) -> None:
    """Append an app notice to the conversation with other changes (one write).

    Args:
        state: The cached session.
        text: Notice text, with untrusted parts already escaped.
        **changes: Other session fields to change.
    """
    message = ChatMessage(role="notice", content=text)
    ui_state.persist(lambda: session_store.save_turn(state, [message], **changes))


def draft_pending(state: SessionState) -> bool:
    """Tell whether the session holds a draft with found tracks not yet saved to Spotify.

    Args:
        state: The cached session.

    Returns:
        True when the draft can still be created.
    """
    created = state.created_playlist
    unsaved = created is None or not created.items_added
    return state.draft is not None and unsaved and any(t.found for t in state.resolved_tracks)


def _logged_in(state: SessionState, tokens: SpotifyTokens) -> None:
    """Store the encrypted tokens, switch to Spotify mode and offer the pending draft.

    Args:
        state: The cached session.
        tokens: The user's tokens with id and display name filled in.
    """
    name = errors.escape_markdown(tokens.display_name or tokens.user_id or "Spotify")
    changes: dict[str, object] = {
        "mode": "spotify",
        "spotify_auth": crypto.encrypt_tokens(tokens),
        "oauth_state": None,
        "pending_action": None,
    }
    text = f"You're logged in as {name}."
    if state.draft is not None and draft_pending(state):
        title = errors.escape_markdown(state.draft.title)
        text = f"You're logged in as {name} — save '{title}' to Spotify?"
        action = PendingAction(kind="confirm_create", message_index=len(state.messages))
        changes["pending_action"] = action
    _notice(state, text, **changes)


def _exchange(state: SessionState, code: str) -> None:
    """Exchange the code, read the profile and log the user in (or explain why not).

    Args:
        state: The cached session whose `state` parameter was verified.
        code: The authorization code.
    """
    client = spotify_client.SpotifyClient()
    try:
        tokens = auth.exchange_code(code)
        profile = client.get_me(tokens.access_token.get_secret_value())
    except SpotifyForbiddenError:
        _logger.info("Spotify login refused: account not on the allowlist")
        _notice(state, errors.INVITE_ONLY, oauth_state=None, pending_action=None)
        return
    except SpotifyError as exc:
        ui_state.flash("error", errors.spotify_error_message(exc))
        return
    finally:
        client.close()
    user_id = str(profile.get("id") or "")
    name = profile.get("display_name") or user_id
    _logged_in(state, tokens.model_copy(update={"user_id": user_id, "display_name": name}))


def handle_callback(screen: str) -> str:
    """Process the OAuth callback once per Streamlit session, if this run carries one.

    Args:
        screen: The screen chosen by the bootstrap.

    Returns:
        The screen to render.
    """
    params = st.query_params
    if not {"code", "error"} & set(params.keys()) or st.session_state.get(CALLBACK_KEY):
        return screen
    st.session_state[CALLBACK_KEY] = True
    code, received, error = params.get("code"), params.get("state"), params.get("error")
    st.query_params.clear()
    state = st.session_state.get(ui_state.STATE_KEY)
    if state is None or screen != "chat":
        ui_state.flash("warning", errors.LOGIN_CANCELLED if error else errors.LOGIN_TOO_SLOW)
        st.session_state[ui_state.SCREEN_KEY] = "landing"
        return "landing"
    if error or not code:
        _notice(state, errors.LOGIN_CANCELLED, oauth_state=None)
    elif not auth.verify_state(state.oauth_state, received):
        _logger.warning("OAuth state mismatch: code not exchanged")
        ui_state.flash("error", errors.LOGIN_CHECK_FAILED)
    else:
        _exchange(state, code)
    return screen
