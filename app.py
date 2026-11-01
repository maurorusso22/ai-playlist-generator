"""Streamlit entry point: session bootstrap, OAuth callback, login redirect and screen routing.

Each run reads localStorage first (the bridge must render on every run), performs the browser
write a callback queued, resolves the screen once per Streamlit session (so reruns cost no
Firestore reads), handles a Spotify callback, drives a pending login redirect, then renders
the landing, chat or expired screen.
"""

import logging

import streamlit as st
from google.api_core.exceptions import GoogleAPIError

from src import browser_session, session_store
from src.config import get_settings
from src.ui import chat, errors, landing, login, oauth_callback, styles
from src.ui import state as ui_state

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger(__name__)


def flush_storage() -> bool:
    """Perform the browser write queued by a callback, if any.

    Returns:
        True when a write was performed in this run (the run's read is then stale).
    """
    op, session_id = st.session_state.pop(ui_state.STORAGE_OP_KEY, (None, None))
    if op == "store":
        browser_session.store_session_id(session_id)
    elif op == "clear":
        browser_session.clear_session_id()
    return op is not None


def bootstrap(ready: bool, session_id: str | None) -> str:
    """Resolve the screen once per Streamlit session, so reruns cost no Firestore reads.

    Args:
        ready: Whether the browser has answered the localStorage read.
        session_id: The stored session id, if any.

    Returns:
        The screen to render.
    """
    if ui_state.SCREEN_KEY in st.session_state:
        return str(st.session_state[ui_state.SCREEN_KEY])
    if not ready:
        st.markdown(styles.equalizer_html(), unsafe_allow_html=True)
        st.caption("Loading your session…")
        st.stop()
    screen = "landing"
    if session_id is not None:
        try:
            status, state = session_store.load_session(session_id)
        except GoogleAPIError:
            _logger.exception("Session load failed")
            st.error(errors.LOAD_FAILED)
            st.stop()
        if status == "active" and state is not None:
            ui_state.set_current(state)
            screen = "chat"
        else:
            browser_session.clear_session_id()
            screen = "expired" if status == "expired" else "landing"
    st.session_state[ui_state.SCREEN_KEY] = screen
    return screen


def render_expired() -> None:
    """Expired screen: a notice and only a New chat button (FR-13)."""
    minutes = get_settings().session_ttl_minutes
    st.info(f"This chat expired after {minutes} minutes of inactivity and was deleted.")
    st.button("New chat", key="expired_new_chat", on_click=ui_state.start_new_chat)


SCREENS = {  # Renderer of each screen name
    "landing": landing.render_landing,
    "chat": chat.render_chat,
    "expired": render_expired,
}


def main() -> None:
    """Run one script pass: bridge read, queued write, bootstrap, callback, login, screen."""
    st.set_page_config(page_title="AI Playlist Generator", page_icon=":material/queue_music:")
    styles.inject_styles()
    ready, session_id = browser_session.read_session_id()
    wrote = flush_storage()
    screen = oauth_callback.handle_callback(bootstrap(ready, session_id))
    login.continue_login(ready, session_id, wrote)
    SCREENS[screen]()


main()
