"""Create the current draft as a private Spotify playlist, idempotently (FR-06, FR-10).

`created_playlist` is cached and stored right after `POST /me/playlists`, so a retry or a
double click resumes at `add_items` and never creates a second playlist; `items_added`
marks the end. A 401 refreshes the token once; a rejected refresh sends the user back to
the login (`login_to_save`).
"""

import logging
from urllib.parse import quote

import streamlit as st
from google.api_core.exceptions import GoogleAPIError

from src import crypto, session_store
from src.models.session.chat_message import ChatMessage
from src.models.session.created_playlist import CreatedPlaylist
from src.models.session.pending_action import PendingAction
from src.models.spotify.spotify_tokens import SpotifyTokens
from src.spotify import auth
from src.spotify import client as spotify_client
from src.spotify.errors import (
    SpotifyAuthError,
    SpotifyError,
    SpotifyForbiddenError,
    SpotifyReauthRequired,
)
from src.ui import errors
from src.ui import state as ui_state

PLAYLIST_URL = "https://open.spotify.com/playlist/{id}"  # Public link of a created playlist
AUTH_ATTEMPTS = 2  # A 401 is retried once, after a token refresh

_logger = logging.getLogger(__name__)


def _save_tokens(tokens: SpotifyTokens) -> SpotifyTokens:
    """Persist refreshed tokens, encrypted, in the cached session.

    Args:
        tokens: The refreshed tokens.

    Returns:
        The same tokens, for chaining.
    """
    state = ui_state.current()
    ui_state.set_current(session_store.touch(state, spotify_auth=crypto.encrypt_tokens(tokens)))
    return tokens


def _create_and_fill(client: spotify_client.SpotifyClient, tokens: SpotifyTokens) -> None:
    """Create the playlist unless already created, add the found tracks, post the link.

    Args:
        client: Spotify Web API client.
        tokens: Fresh user tokens.
    """
    state, token = ui_state.current(), tokens.access_token.get_secret_value()
    created, draft = state.created_playlist, state.draft
    if draft is None:
        return
    if created is None:
        playlist_id = str(client.create_playlist(token, draft.title, draft.description)["id"])
        created = CreatedPlaylist(id=playlist_id, url=PLAYLIST_URL.format(id=quote(playlist_id)))
        state = state.model_copy(update={"created_playlist": created})
        ui_state.set_current(state)  # Cached before the write: a failed write cannot duplicate
        state = session_store.touch(state, created_playlist=created)
        ui_state.set_current(state)
    uris = [track.uri for track in state.resolved_tracks if track.found and track.uri]
    client.add_items(token, created.id, uris)
    done = created.model_copy(update={"items_added": True})
    ui_state.set_current(state.model_copy(update={"created_playlist": done}))
    title = errors.escape_markdown(draft.title)
    text = f"Saved **{title}** to Spotify with {len(uris)} tracks: {created.url}"
    notice = ChatMessage(role="notice", content=text)
    if ui_state.persist(
        lambda: session_store.save_turn(state, [notice], created_playlist=done, pending_action=None)
    ):
        st.session_state[ui_state.CELEBRATE_KEY] = True


def _run(tokens: SpotifyTokens) -> None:
    """Refresh if needed, then create and fill, refreshing once more on a 401.

    Args:
        tokens: The user's stored tokens.
    """
    fresh = auth.ensure_fresh(tokens)
    tokens = _save_tokens(fresh) if fresh is not tokens else tokens
    client = spotify_client.SpotifyClient()
    try:
        for attempt in range(1, AUTH_ATTEMPTS + 1):
            try:
                _create_and_fill(client, tokens)
                return
            except SpotifyAuthError:
                if attempt == AUTH_ATTEMPTS:
                    raise
                tokens = _save_tokens(auth.refresh_tokens(tokens))
    finally:
        client.close()


def _logout(text: str, offer_login: bool) -> None:
    """Drop the Spotify login, post a notice and optionally offer the login button again.

    Args:
        text: Notice text.
        offer_login: Whether to show "Log in with Spotify to save" under the notice.
    """
    state = ui_state.current()
    pending = PendingAction(kind="login_to_save", message_index=len(state.messages))
    notice = ChatMessage(role="notice", content=text)
    changes = {
        "mode": "guest",
        "spotify_auth": None,
        "pending_action": pending if offer_login else None,
    }
    ui_state.persist(lambda: session_store.save_turn(state, [notice], **changes))


def create_on_spotify() -> None:
    """Handle a "Create on Spotify" click on the cached session; errors keep the buttons."""
    state = ui_state.active()
    if state is None:
        return
    created = state.created_playlist
    if created is not None and created.items_added:
        ui_state.flash("info", f"Your playlist is already on Spotify: {created.url}")
        return
    tokens = crypto.decrypt_tokens(state.spotify_auth) if state.spotify_auth else None
    if tokens is None:  # Never logged in here, or the encryption key was rotated
        _logout(errors.LOGIN_EXPIRED, offer_login=True)
        return
    try:
        _run(tokens)
    except (SpotifyAuthError, SpotifyReauthRequired) as exc:
        _logger.info("Spotify login needed again: %s", exc.message)
        _logout(errors.LOGIN_EXPIRED, offer_login=True)
    except SpotifyForbiddenError:
        _logout(errors.INVITE_ONLY, offer_login=False)
    except SpotifyError as exc:
        ui_state.flash("warning", errors.spotify_error_message(exc))
    except GoogleAPIError:
        _logger.exception("Firestore write failed during playlist creation")
        ui_state.flash("error", errors.SAVE_FAILED)
