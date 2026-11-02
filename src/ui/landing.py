"""Landing screen (FR-01): logo, headline, three steps, the two entry points and the notes."""

import html
import logging

import streamlit as st
from google.api_core.exceptions import GoogleAPIError

from src.session import session_store
from src.ui import errors, login, styles
from src.ui import state as ui_state

HEADLINE = "Describe the music you want"  # Hero heading; its period is drawn in the accent color
TAGLINE = "Get a Spotify-ready playlist in seconds."  # Line under the hero heading
STEPS = (  # Title and text of the three numbered steps
    ("Describe", "A genre, a mood, an era, an artist, an album or a song."),
    ("Review", "Refine the draft in the chat until it sounds right."),
    ("Save", "Create it as a private playlist on your Spotify account."),
)
INFO_ICON = (  # Stroke icon in front of the notes, decorative
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" aria-hidden="true">'
    '<circle cx="12" cy="12" r="9"></circle><path d="M12 11v5M12 8h.01"></path></svg>'
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
    """Build the brand line, the hero heading and the numbered steps (static text only).

    Returns:
        The landing markup.
    """
    steps = "".join(
        f'<li><span class="apg-step-num">{number}</span>'
        f'<span class="apg-step-title">{title}</span>'
        f'<span class="apg-step-text">{text}</span></li>'
        for number, (title, text) in enumerate(STEPS, start=1)
    )
    return (
        f'{styles.brand_html(large=True)}<div class="apg-hero">'
        f'<div class="apg-hero-title" role="heading" aria-level="1">{HEADLINE}<span>.</span></div>'
        f'<div class="apg-tagline">{TAGLINE}</div></div>'
        f'<ol class="apg-steps">{steps}</ol>'
    )


def notes_html() -> str:
    """Build the invite-only and privacy notes shown under the entry points.

    Returns:
        The notes box markup.
    """
    notes = "".join(f"<p>{html.escape(note)}</p>" for note in (INVITE_NOTE, PRIVACY_NOTE))
    return f'<div class="apg-notes">{INFO_ICON}<div>{notes}</div></div>'


def render_landing() -> None:
    """Render the landing screen with exactly two buttons."""
    ui_state.render_flash()
    st.markdown(hero_html(), unsafe_allow_html=True)
    spotify, guest = st.columns(2)
    spotify.button(
        "Continue with Spotify", key="landing_spotify", on_click=login.start_login, width="stretch"
    )
    guest.button("Use as a Guest", key="landing_guest", on_click=start_guest, width="stretch")
    st.markdown(notes_html(), unsafe_allow_html=True)
