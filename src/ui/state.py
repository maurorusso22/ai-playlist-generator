"""Per-tab UI state in `st.session_state`: the cached session, flash messages, lifecycle.

Widget callbacks run before the script, where the localStorage bridge cannot render, so they
queue browser writes (STORAGE_OP_KEY) that the next run performs. Session-store functions
are used as module attributes so tests can patch them.
"""

import logging
from collections.abc import Callable
from typing import Literal

import streamlit as st
from google.api_core.exceptions import GoogleAPIError

from src.models.session.session_state import SessionState
from src.session import browser_session, session_store
from src.ui import errors

SCREEN_KEY = "screen"  # Cached bootstrap result: "landing", "chat" or "expired"
STATE_KEY = "session"  # Cached SessionState of the open conversation
STORAGE_OP_KEY = "storage_op"  # Queued browser write: ("store", id) or ("clear", None)
CHAT_INPUT_KEY = "chat_text"  # Widget key of the chat input
FLASH_KEY = "flash"  # Transient messages shown once on the next render
CELEBRATE_KEY = "celebrate"  # Set after a playlist is created: confetti on the next run

FlashKind = Literal["info", "warning", "error"]  # Streamlit alert used to show a flash

_logger = logging.getLogger(__name__)


def current() -> SessionState:
    """Return the cached session of this tab.

    Returns:
        The cached SessionState (only call on screens that have one).
    """
    state: SessionState = st.session_state[STATE_KEY]
    return state


def set_current(state: SessionState) -> None:
    """Cache the session state written last.

    Args:
        state: The new session state.
    """
    st.session_state[STATE_KEY] = state


def flash(kind: FlashKind, text: str) -> None:
    """Queue a transient message for the next render.

    Args:
        kind: Alert type.
        text: Message text, already escaped when it contains untrusted parts.
    """
    st.session_state.setdefault(FLASH_KEY, []).append((kind, text))


def render_flash() -> None:
    """Show and discard the queued transient messages."""
    for kind, text in st.session_state.pop(FLASH_KEY, []):
        {"info": st.info, "warning": st.warning, "error": st.error}[kind](text)


def persist(write: Callable[[], SessionState]) -> bool:
    """Run one session-store write and cache its result; Firestore errors become a flash.

    Args:
        write: A call to `session_store.save_turn` or `session_store.touch`.

    Returns:
        True when the write succeeded.
    """
    try:
        set_current(write())
    except GoogleAPIError:
        _logger.exception("Firestore write failed")
        flash("error", errors.SAVE_FAILED)
        return False
    return True


def expire(state: SessionState) -> None:
    """Delete an expired session and switch to the expired screen (FR-13).

    Args:
        state: The cached session found expired.
    """
    try:
        session_store.delete_session(state.session_id)
    except GoogleAPIError:
        _logger.warning("Could not delete expired session %s; TTL will", state.session_id)
    st.session_state.pop(STATE_KEY, None)
    st.session_state[SCREEN_KEY] = "expired"
    st.session_state[STORAGE_OP_KEY] = ("clear", None)


def active() -> SessionState | None:
    """Return the cached session if still valid, expiring it otherwise (no Firestore read).

    Returns:
        The active session, or None when there is none or it just expired.
    """
    state: SessionState | None = st.session_state.get(STATE_KEY)
    if state is not None and session_store.is_expired(state):
        expire(state)
        return None
    return state


def start_new_chat() -> None:
    """Callback of "New chat": delete the document, reset the tab state, back to landing."""
    state = st.session_state.get(STATE_KEY)
    if state is not None:
        try:
            session_store.delete_session(state.session_id)
        except GoogleAPIError:
            _logger.exception("Session delete failed")
            flash("error", errors.DELETE_FAILED)
            return
    for key in [k for k in st.session_state if not k.startswith(browser_session.BRIDGE_KEY_PREFIX)]:
        del st.session_state[key]
    st.session_state[SCREEN_KEY] = "landing"
    if state is not None:
        st.session_state[STORAGE_OP_KEY] = ("clear", None)
