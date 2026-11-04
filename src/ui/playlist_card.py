"""Compact, expandable playlist card (FR-05) with Spotify attribution.

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
from src.ui.spotify_markup import IMAGE_URL_PREFIX, TRACK_URL_PREFIX, safe_url, spotify_logo_html

COLLAPSED_ROWS = 5  # Rows visible before the "Show all" expander
COVER_PX = 56  # Rendered album cover size
CARD_KEY = "playlist_card"  # Container key; styles.css draws the card on its st-key class
ATTRIBUTION = "Metadata provided by Spotify"  # Text attribution required near Spotify content


def track_row_html(track: ResolvedTrack, index: int) -> str:
    """Build one track row: number, cover, title (linked to Spotify) and artists.

    A row without artwork gets a dashed placeholder; the artwork itself is never styled.

    Args:
        track: A resolved track.
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
    link = safe_url(track.external_url, TRACK_URL_PREFIX)
    if link:
        title = f'<a href="{link}" target="_blank" rel="noopener noreferrer">{title}</a>'
    return (
        f'<div class="apg-row" style="--i:{int(index)}">'
        f'<span class="apg-num">{int(index) + 1}</span>{cover}'
        f'<div class="apg-track"><div class="apg-title">{title}</div>'
        f'<div class="apg-artist">{artists}</div></div></div>'
    )


def card_header_html(draft: PlaylistDraft, tracks: list[ResolvedTrack], saved: bool) -> str:
    """Build the card header: status chip, title, description and the track count.

    Args:
        draft: The LLM's draft (title and description).
        tracks: Resolved tracks.
        saved: Whether the playlist is already created on Spotify with its tracks.

    Returns:
        The escaped header markup.
    """
    meta = f"{len(tracks)} tracks"
    chip = "On Spotify" if saved else "Draft"
    return (
        f'<div class="apg-card-head"><div><span class="apg-chip">{chip}</span></div>'
        f'<div class="apg-card-title">{html.escape(draft.title)}</div>'
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
    logo = spotify_logo_html()
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
