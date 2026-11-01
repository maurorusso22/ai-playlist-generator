"""Landing screen (FR-01): logo, tagline, three steps and the two entry points."""

import logging

import streamlit as st
from google.api_core.exceptions import GoogleAPIError

from src.session import session_store
from src.ui import errors, login, styles
from src.ui import state as ui_state

TAGLINE = "Describe the music you want. Get a Spotify-ready playlist in seconds."  # Hero line
STEPS = (  # Title and text of the three step cards
    ("1 · Describe", "A genre, a mood, an era, an artist, an album or a song."),
    ("2 · Review", "Refine the draft in the chat until it sounds right."),
    ("3 · Save", "Create it as a private playlist on your Spotify account."),
)
INVITE_NOTE = (  # Spotify Development Mode limit, explained before the login
    "Spotify login is invite-only (development mode, up to 5 users). "
    "Everyone else can use guest mode and still get Spotify-ready playlists."
)
PRIVACY_NOTE = (  # Free-tier prompts may be used by Google to improve its products
    "Please don't share personal data: this demo runs on the Gemini free tier, "
    "whose prompts may be used by Google to improve its products."
)

_logger = logging.getLogger(__name__)


def start_guest() -> None:
    """Callback of "Use as a Guest": create the session and queue the id write."""
    try:
        state = session_store.create_session("guest")
    except GoogleAPIError:
        _logger.exception("Session creation failed")
        ui_state.flash("error", errors.SAVE_FAILED)
        return
    ui_state.set_current(state)
    st.session_state[ui_state.SCREEN_KEY] = "chat"
    st.session_state[ui_state.STORAGE_OP_KEY] = ("store", state.session_id)


def hero_html() -> str:
    """Build the hero block and the three step cards (static text only).

    Returns:
        The landing markup.
    """
    steps = "".join(
        f'<div class="apg-step"><div class="apg-step-title">{title}</div>'
        f'<div class="apg-step-text">{text}</div></div>'
        for title, text in STEPS
    )
    return (
        f'<div class="apg-hero">{styles.logo_html(88)}'
        '<div class="apg-hero-name">AI Playlist Generator</div>'
        f'<div class="apg-tagline">{TAGLINE}</div></div>'
        f'<div class="apg-steps">{steps}</div>'
    )


def render_landing() -> None:
    """Render the landing screen with exactly two buttons."""
    ui_state.render_flash()
    st.markdown(hero_html(), unsafe_allow_html=True)
    spotify, guest = st.columns(2)
    spotify.button(
        "Continue with Spotify", key="landing_spotify", on_click=login.start_login, width="stretch"
    )
    guest.button("Use as a Guest", key="landing_guest", on_click=start_guest, width="stretch")
    st.caption(INVITE_NOTE)
    st.caption(PRIVACY_NOTE)
