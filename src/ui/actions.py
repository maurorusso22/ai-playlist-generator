"""Non-blocking confirmation buttons under the latest message (FR-06, FR-07, FR-08).

Buttons render only under the message their pending action is bound to, and only when it is
the latest one, so a new message (which clears the action) makes them disappear. The create
click only flags the request: the script run then shows the buttons disabled while the
Spotify calls run, so a second click cannot start a second creation.
"""

import streamlit as st

from src import session_store
from src.models.session.session_state import SessionState
from src.ui import login, spotify_save
from src.ui import state as ui_state

CREATE_KEY = "create_requested"  # Message index whose "Create on Spotify" was clicked


def request_create(message_index: int) -> None:
    """Callback of "Create on Spotify": flag the request for the next script run.

    Args:
        message_index: Index of the message the buttons belong to.
    """
    st.session_state[CREATE_KEY] = message_index


def not_now() -> None:
    """Callback of "Not now": dismiss the buttons (one write that also slides the expiry)."""
    state = ui_state.active()
    if state is not None:
        ui_state.persist(lambda: session_store.touch(state, pending_action=None))


def _confirm_buttons(index: int, busy: bool) -> None:
    """Render "Create on Spotify" and "Not now".

    Args:
        index: Message index the buttons belong to, part of their keys.
        busy: Whether a creation is running (buttons disabled).
    """
    left, right = st.columns(2)
    left.button(
        "Create on Spotify",
        key=f"create_{index}",
        type="primary",
        disabled=busy,
        on_click=request_create,
        args=(index,),
        width="stretch",
    )
    right.button(
        "Not now", key=f"not_now_{index}", disabled=busy, on_click=not_now, width="stretch"
    )


def render_actions(state: SessionState) -> None:
    """Render the pending action's buttons under the latest message, running a requested create.

    Args:
        state: The cached session.
    """
    action = state.pending_action
    last = len(state.messages) - 1
    if action is None or action.message_index != last:
        return
    if action.kind == "login_to_save":
        st.button(
            "Log in with Spotify to save", key=f"login_to_save_{last}", on_click=login.start_login
        )
        return
    busy = st.session_state.get(CREATE_KEY) == last
    _confirm_buttons(last, busy)
    if not busy:
        return
    try:
        with st.spinner("Creating your playlist on Spotify…"):
            spotify_save.create_on_spotify()
    finally:
        st.session_state.pop(CREATE_KEY, None)
    st.rerun()
