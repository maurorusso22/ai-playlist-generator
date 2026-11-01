"""Compact, expandable playlist card (FR-05) with not-found flags (FR-16) and attribution.

This is the only place where LLM- and Spotify-derived text meets raw HTML, so every dynamic
field goes through `html.escape` and only Spotify's own link and image hosts are accepted:
this closes the chain prompt injection -> XSS -> localStorage session theft. Album artwork is
rendered unaltered: the <img> tag carries no style, class, filter or animation.
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
COVER_PX = 64  # Rendered album cover size
SPOTIFY_LOGOS = (  # Official Spotify logo files, added by hand; the first present is shown
    styles.PUBLIC_DIR / "spotify_logo.svg",
    styles.PUBLIC_DIR / "spotify_logo.png",
)
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
    """Build one track row: cover, title (linked to Spotify), artists and not-found badge.

    Args:
        track: A resolved (or flagged not-found) track.
        index: Position in the card, used for the staggered fade-in delay.

    Returns:
        The escaped row markup on a single line.
    """
    title = html.escape(track.name)
    artists = html.escape(", ".join(track.artists))
    image = safe_url(track.image_url, IMAGE_URL_PREFIX)
    alt = html.escape(track.album or track.name, quote=True)
    cover = (
        f'<img src="{image}" alt="{alt}" width="{COVER_PX}" height="{COVER_PX}">' if image else ""
    )
    link = safe_url(track.external_url, TRACK_URL_PREFIX) if track.found else None
    if link:
        title = f'<a href="{link}" target="_blank" rel="noopener noreferrer">{title}</a>'
    badge = "" if track.found else '<span class="apg-missing-badge">not found on Spotify</span>'
    row_class = "apg-row" if track.found else "apg-row apg-missing"
    return (
        f'<div class="{row_class}" style="--i:{int(index)}"><div class="apg-cover">{cover}</div>'
        f'<div class="apg-track"><div class="apg-title">{title}</div>'
        f'<div class="apg-artist">{artists}</div></div>{badge}</div>'
    )


def card_header_html(draft: PlaylistDraft, tracks: list[ResolvedTrack]) -> str:
    """Build the card header: title, description and the found/not-found counts.

    Args:
        draft: The LLM's draft (title and description).
        tracks: Resolved tracks, not-found entries included.

    Returns:
        The escaped header markup.
    """
    found = sum(track.found for track in tracks)
    missing = len(tracks) - found
    meta = f"{found} tracks" + (f" · {missing} not found on Spotify" if missing else "")
    return (
        f'<div class="apg-card-head"><div class="apg-card-title">{html.escape(draft.title)}</div>'
        f'<div class="apg-card-desc">{html.escape(draft.description)}</div>'
        f'<div class="apg-card-meta">{meta}</div></div>'
    )


def attribution_html(created: CreatedPlaylist | None) -> str:
    """Build the Spotify attribution line, with the playlist link once it is created.

    Args:
        created: The playlist created on Spotify, if any.

    Returns:
        The attribution markup.
    """
    logo_uri = next(filter(None, map(styles.data_uri, SPOTIFY_LOGOS)), None)
    logo = f'<img src="{logo_uri}" alt="Spotify" height="24">' if logo_uri else ""
    link = safe_url(created.url, TRACK_URL_PREFIX) if created and created.items_added else None
    anchor = (
        f' · <a href="{link}" target="_blank" rel="noopener">Open on Spotify</a>' if link else ""
    )
    return f'<div class="apg-attrib">{logo}<span>{ATTRIBUTION}{anchor}</span></div>'


def render_playlist_card(state: SessionState) -> None:
    """Render the card of the current draft under its message.

    The first COLLAPSED_ROWS rows are always visible; the expander holding the rest is
    rendered only when there are more rows than that.

    Args:
        state: The session holding the draft and its resolved tracks.
    """
    if state.draft is None:
        return
    tracks = state.resolved_tracks
    rows = [track_row_html(track, index) for index, track in enumerate(tracks)]
    head = card_header_html(state.draft, tracks)
    visible = "".join(rows[:COLLAPSED_ROWS])
    st.markdown(f'<div class="apg-card">{head}{visible}</div>', unsafe_allow_html=True)
    if len(rows) > COLLAPSED_ROWS:
        with st.expander(f"Show all {len(rows)} tracks"):
            st.markdown("".join(rows[COLLAPSED_ROWS:]), unsafe_allow_html=True)
    st.markdown(attribution_html(state.created_playlist), unsafe_allow_html=True)
