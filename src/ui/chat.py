"""Chat screen: header with mode badge, history with card and buttons, chat input.

LLM and Spotify text is rendered with plain `st.markdown` (never `unsafe_allow_html`); the
only raw HTML comes from the playlist card, which escapes every field.
"""

import streamlit as st

from src.models.session.session_state import SessionState
from src.session import crypto
from src.ui import actions, errors, login, playlist_card, styles, turn
from src.ui import state as ui_state

WELCOME = (  # First assistant bubble of an empty chat (not stored, never sent to the LLM)
    "Tell me what you'd like to listen to: a genre, a mood, a year or era, an artist, "
    "an album or a song. I'll draft a playlist you can review before saving it."
)
NOTICE_AVATAR = ":material/info:"  # Avatar of app notices (login, links, errors)


def mode_label(state: SessionState) -> str:
    """Build the mode badge text: `Guest` or `Spotify · <display name>`.

    Args:
        state: The cached session.

    Returns:
        The badge label, with the Spotify display name escaped.
    """
    if state.mode != "spotify":
        return "Guest"
    tokens = crypto.decrypt_tokens(state.spotify_auth) if state.spotify_auth else None
    name = tokens.display_name if tokens is not None else None
    return f"Spotify · {errors.escape_markdown(name)}" if name else "Spotify"


def _header(state: SessionState) -> None:
    """Render the brand, the mode badge, the guest login button and New chat.

    Args:
        state: The cached session.
    """
    # A wrapping flex row: the brand takes the free space, the rest sizes to its content.
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown(styles.brand_html(), unsafe_allow_html=True, width="stretch")
        st.badge(mode_label(state), icon=":material/account_circle:", color="gray")
        if state.mode == "guest":
            st.button("Log in with Spotify", key="header_login", on_click=login.start_login)
        st.button("New chat", key="new_chat", on_click=ui_state.start_new_chat)


def _history(state: SessionState, show_actions: bool) -> None:
    """Render the stored messages with the card under its draft message.

    Args:
        state: The cached session.
        show_actions: False while a new message is processed (it dismisses the buttons).
    """
    if not state.messages:
        with st.chat_message("assistant", avatar=turn.ASSISTANT_AVATAR):
            st.markdown(WELCOME)
    last = len(state.messages) - 1
    for index, message in enumerate(state.messages):
        role = "user" if message.role == "user" else "assistant"
        avatar = {"user": None, "assistant": turn.ASSISTANT_AVATAR}.get(message.role, NOTICE_AVATAR)
        with st.chat_message(role, avatar=avatar):
            st.markdown(message.content)
            if index == state.draft_message_index:
                playlist_card.render_playlist_card(state)
            if show_actions and index == last:
                actions.render_actions(state)


def render_chat() -> None:
    """Render the chat screen and process a submitted message."""
    state = ui_state.current()
    _header(state)
    text = st.chat_input("Describe your playlist…", key=ui_state.CHAT_INPUT_KEY)
    _history(state, show_actions=not text)
    ui_state.render_flash()
    if st.session_state.pop(ui_state.CELEBRATE_KEY, False):
        styles.celebrate()
    if text:
        turn.handle_user_message(text)
