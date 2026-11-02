"""Compact, expandable playlist card (FR-05) with not-found flags (FR-16) and attribution.

This is the only place where LLM- and Spotify-derived text meets raw HTML, so every dynamic
field goes through `html.escape` and only Spotify's own link and image hosts are accepted:
this closes the chain prompt injection -> XSS -> localStorage session theft. Album artwork is
rendered in its original form: the <img> tag carries no style, class, filter or animation, and
the stylesheet only rounds its corners by the 4px Spotify's design guidelines require.
"""

import html

import streamlit as st

from src.models.conversation.playlist_draft import PlaylistDraft
from src.models.session.created_playlist import CreatedPlaylist
from src.models.session.session_state import SessionState
from src.models.spotify.resolved_track import ResolvedTrack
from src.ui import styles

TRACK_URL_PREFIX = "https://open.spotify.com/"  # Only links to Spotify's web player are kept
IMAGE_URL_PREFIX = "https://i.scdn.co/"  # Only Spotify's image CDN is kept
COLLAPSED_ROWS = 5  # Rows visible before the "Show all" expander
COVER_PX = 56  # Rendered album cover size
CARD_KEY = "playlist_card"  # Container key; styles.css draws the card on its st-key class
SPOTIFY_LOGOS = (  # Official full logos, unmodified: (CSS theme class, file) per surface
    ("light", styles.PUBLIC_DIR / "spotify_logo_black.svg"),
    ("dark", styles.PUBLIC_DIR / "spotify_logo_white.svg"),
)
LOGO_PX = 24  # Full logo height; its width (~88px) stays above Spotify's 70px minimum
ATTRIBUTION = "Metadata provided by Spotify"  # Text attribution required near Spotify content


def safe_url(url: str | None, prefix: str) -> str | None:
    """Accept a URL only on an allowlisted host, escaped for an HTML attribute.

    Args:
        url: URL coming from Spotify data.
        prefix: Required scheme, host and leading slash.

    Returns:
        The escaped URL, or None when it is missing or not allowlisted.
    """
    if not url or not url.startswith(prefix):
        return None
    return html.escape(url, quote=True)


def track_row_html(track: ResolvedTrack, index: int) -> str:
    """Build one track row: number, cover, title (linked to Spotify), artists, not-found badge.

    A row without artwork gets a dashed placeholder; the artwork itself is never styled.

    Args:
        track: A resolved (or flagged not-found) track.
        index: Position in the card, used for the number and the staggered fade-in delay.

    Returns:
        The escaped row markup on a single line.
    """
    title = html.escape(track.name)
    artists = html.escape(", ".join(track.artists))
    image = safe_url(track.image_url, IMAGE_URL_PREFIX)
    alt = html.escape(track.album or track.name, quote=True)
    cover = (
        f'<div class="apg-cover"><img src="{image}" alt="{alt}" '
        f'width="{COVER_PX}" height="{COVER_PX}"></div>'
        if image
        else '<div class="apg-cover apg-cover-empty" aria-hidden="true"></div>'
    )
    link = safe_url(track.external_url, TRACK_URL_PREFIX) if track.found else None
    if link:
        title = f'<a href="{link}" target="_blank" rel="noopener noreferrer">{title}</a>'
    badge = "" if track.found else '<span class="apg-missing-badge">Not on Spotify</span>'
    row_class = "apg-row" if track.found else "apg-row apg-missing"
    return (
        f'<div class="{row_class}" style="--i:{int(index)}">'
        f'<span class="apg-num">{int(index) + 1}</span>{cover}'
        f'<div class="apg-track"><div class="apg-title">{title}</div>'
        f'<div class="apg-artist">{artists}</div>{badge}</div></div>'
    )


def card_header_html(draft: PlaylistDraft, tracks: list[ResolvedTrack], saved: bool) -> str:
    """Build the card header: status chip, title, description and the found/not-found counts.

    Args:
        draft: The LLM's draft (title and description).
        tracks: Resolved tracks, not-found entries included.
        saved: Whether the playlist is already created on Spotify with its tracks.

    Returns:
        The escaped header markup.
    """
    found = sum(track.found for track in tracks)
    missing = len(tracks) - found
    meta = f"{found} tracks" + (f" · {missing} not found on Spotify" if missing else "")
    chip = "On Spotify" if saved else "Draft"
    return (
        f'<div class="apg-card-head"><div><span class="apg-chip">{chip}</span></div>'
        f'<div class="apg-card-title">{html.escape(draft.title)}</div>'
        f'<div class="apg-card-desc">{html.escape(draft.description)}</div>'
        f'<div class="apg-card-meta">{meta}</div></div>'
    )


def attribution_html(created: CreatedPlaylist | None) -> str:
    """Build the Spotify attribution line, with the playlist link once it is created.

    Both logo variants are emitted; the stylesheet shows the one matching the color scheme.

    Args:
        created: The playlist created on Spotify, if any.

    Returns:
        The attribution markup.
    """
    uris = ((theme, styles.data_uri(path)) for theme, path in SPOTIFY_LOGOS)
    logo = "".join(
        f'<img class="apg-logo-{theme}" src="{uri}" alt="Spotify" height="{LOGO_PX}">'
        for theme, uri in uris
        if uri
    )
    link = safe_url(created.url, TRACK_URL_PREFIX) if created and created.items_added else None
    anchor = (
        f' · <a href="{link}" target="_blank" rel="noopener">Open on Spotify</a>' if link else ""
    )
    return f'<div class="apg-attrib">{logo}<span>{ATTRIBUTION}{anchor}</span></div>'


def render_playlist_card(state: SessionState) -> None:
    """Render the card of the current draft under its message.

    The first COLLAPSED_ROWS rows are always visible; the expander holding the rest is
    rendered only when there are more rows than that. A keyed container draws the card, so
    the expander and the attribution sit inside it.

    Args:
        state: The session holding the draft and its resolved tracks.
    """
    if state.draft is None:
        return
    tracks, created = state.resolved_tracks, state.created_playlist
    rows = [track_row_html(track, index) for index, track in enumerate(tracks)]
    head = card_header_html(state.draft, tracks, saved=bool(created and created.items_added))
    with st.container(key=CARD_KEY):
        st.markdown(f"{head}{''.join(rows[:COLLAPSED_ROWS])}", unsafe_allow_html=True)
        if len(rows) > COLLAPSED_ROWS:
            with st.expander(f"Show all {len(rows)} tracks"):
                st.markdown("".join(rows[COLLAPSED_ROWS:]), unsafe_allow_html=True)
        st.markdown(attribution_html(created), unsafe_allow_html=True)
