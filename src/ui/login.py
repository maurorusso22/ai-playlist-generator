"""Start of the Spotify login: OAuth state, session id read-back, same-tab redirect.

The redirect happens only after the browser reads back the stored session id: otherwise the
callback would land in a new Streamlit session that cannot find the conversation. Each write
mounts a fresh bridge component, so the read of the run that performs it is stale.
"""

import html
import logging

import streamlit as st
from google.api_core.exceptions import GoogleAPIError

from src import browser_session, session_store
from src.spotify import auth
from src.ui import errors, styles
from src.ui import state as ui_state

LOGIN_KEY = "login_pending"  # (session id, extra write attempts) awaiting localStorage read-back
REDIRECT_KEY = "login_redirect"  # Authorize URL the tab is navigating to
MAX_STORE_ATTEMPTS = 2  # Extra session id writes before giving up (blocked storage)

_logger = logging.getLogger(__name__)


def start_login() -> None:
    """Callback of every Spotify login button: create or load the session, store the state."""
    current = ui_state.active()
    if st.session_state.get(ui_state.SCREEN_KEY) == "expired":
        return
    try:
        if current is None:
            current = session_store.create_session("guest")
        current = session_store.touch(current, oauth_state=auth.new_oauth_state())
    except GoogleAPIError:
        _logger.exception("Could not store the OAuth state")
        ui_state.flash("error", errors.SAVE_FAILED)
        return
    ui_state.set_current(current)
    st.session_state[ui_state.SCREEN_KEY] = "chat"
    st.session_state[ui_state.STORAGE_OP_KEY] = ("store", current.session_id)
    st.session_state[LOGIN_KEY] = (current.session_id, 0)


def cancel_login() -> None:
    """Callback of "Cancel": abandon the pending redirect."""
    st.session_state.pop(LOGIN_KEY, None)
    st.session_state.pop(REDIRECT_KEY, None)


def _waiting(title: str, link: str | None = None) -> None:
    """Render the interstitial shown while the login redirect is prepared, then stop the run.

    Args:
        title: Short status line.
        link: Authorize URL for a manual same-tab link, when the script redirect was tried.
    """
    st.markdown(styles.equalizer_html(), unsafe_allow_html=True)
    st.caption(title)
    if link is not None:
        href, style = html.escape(link, quote=True), browser_session.FALLBACK_STYLE
        anchor = (
            f'<a href="{href}" target="_self" style="{style}">{browser_session.FALLBACK_LABEL}</a>'
        )
        st.markdown(anchor, unsafe_allow_html=True)
    st.button("Cancel", key="cancel_login", on_click=cancel_login)
    st.stop()


def continue_login(ready: bool, session_id: str | None, wrote: bool) -> None:
    """Drive a pending login: wait for the read-back, retry the write, then redirect.

    Args:
        ready: Whether the localStorage read of this run has answered.
        session_id: The session id read in this run.
        wrote: Whether this run already performed a browser write (its read is stale).
    """
    if REDIRECT_KEY in st.session_state:
        _waiting("Redirecting to Spotify…", st.session_state[REDIRECT_KEY])
    pending = st.session_state.get(LOGIN_KEY)
    if pending is None:
        return
    expected, attempts = pending
    if ready and not wrote and session_id == expected:
        del st.session_state[LOGIN_KEY]
        url = auth.build_authorize_url(ui_state.current().oauth_state or "")
        st.session_state[REDIRECT_KEY] = url
        st.caption("Redirecting to Spotify…")
        browser_session.redirect_same_tab(url)
        st.stop()
    if ready and not wrote:
        if attempts >= MAX_STORE_ATTEMPTS:
            del st.session_state[LOGIN_KEY]
            ui_state.flash("warning", errors.STORAGE_BLOCKED)
            return
        browser_session.store_session_id(expected)
        st.session_state[LOGIN_KEY] = (expected, attempts + 1)
    _waiting("Connecting to Spotify…")
