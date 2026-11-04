"""Card of a playlist saved on Spotify, shown in place of the plain link notice.

Same safety rules as the draft card: every dynamic field goes through `html.escape` and only
Spotify's link and image hosts are accepted. The cover mirrors Spotify's own mosaic (four
distinct album covers, else the first one); each artwork is shown whole and unstyled.
"""

import html

import streamlit as st

from src.models.conversation.playlist_draft import PlaylistDraft
from src.models.session.saved_playlist import SavedPlaylist
from src.models.spotify.resolved_track import ResolvedTrack
from src.ui.spotify_markup import IMAGE_URL_PREFIX, TRACK_URL_PREFIX, safe_url, spotify_logo_html

MOSAIC_TILES = 4  # Distinct covers needed for a 2x2 mosaic, as Spotify does
COVER_PX = 128  # Rendered size of the whole cover (single image or mosaic)
MS_PER_MINUTE = 60_000  # Milliseconds in a minute


def build_saved_playlist(
    draft: PlaylistDraft, tracks: list[ResolvedTrack], url: str, owner: str | None
) -> SavedPlaylist:
    """Snapshot what the saved card shows from the draft and the tracks actually added.

    Args:
        draft: The saved draft (title and description).
        tracks: Resolved tracks; only those with a URI were added to the playlist.
        url: Public link of the created playlist.
        owner: The user's Spotify display name, if known.

    Returns:
        The saved-playlist snapshot.
    """
    added = [track for track in tracks if track.uri]
    images = [track.image_url for track in added if safe_url(track.image_url, IMAGE_URL_PREFIX)]
    distinct = list(dict.fromkeys(url for url in images if url))
    covers = distinct[:MOSAIC_TILES] if len(distinct) >= MOSAIC_TILES else distinct[:1]
    durations = [track.duration_ms for track in added if track.duration_ms]
    return SavedPlaylist(
        url=url,
        title=draft.title,
        description=draft.description,
        track_count=len(added),
        duration_ms=sum(durations) if durations else None,
        owner=owner,
        cover_urls=covers,
    )


def format_duration(duration_ms: int) -> str:
    """Format a total duration the way Spotify does, e.g. "1 h 5 min" or "42 min".

    Args:
        duration_ms: Total duration in milliseconds.

    Returns:
        The human-readable duration.
    """
    hours, minutes = divmod(max(1, round(duration_ms / MS_PER_MINUTE)), 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


def cover_html(saved: SavedPlaylist) -> str:
    """Build the cover: a 2x2 mosaic, a single artwork, or a dashed placeholder.

    Args:
        saved: The saved-playlist snapshot.

    Returns:
        The escaped cover markup.
    """
    urls = [url for url in (safe_url(raw, IMAGE_URL_PREFIX) for raw in saved.cover_urls) if url]
    if not urls:
        return '<div class="apg-saved-cover apg-cover-empty" aria-hidden="true"></div>'
    urls = urls[:MOSAIC_TILES] if len(urls) >= MOSAIC_TILES else urls[:1]
    size = COVER_PX // 2 if len(urls) > 1 else COVER_PX
    images = "".join(f'<img src="{url}" alt="" width="{size}" height="{size}">' for url in urls)
    label = html.escape(f"Cover of {saved.title}", quote=True)
    return f'<div class="apg-saved-cover" role="img" aria-label="{label}">{images}</div>'


def saved_card_html(saved: SavedPlaylist) -> str:
    """Build the saved card: cover, title, description, details and "Open on Spotify".

    Args:
        saved: The saved-playlist snapshot.

    Returns:
        The escaped card markup on a single line (Markdown would turn indents into code).
    """
    details = [f"{saved.track_count} tracks"]
    if saved.owner:
        details.insert(0, f"by {saved.owner}")
    if saved.duration_ms:
        details.append(format_duration(saved.duration_ms))
    meta = html.escape(" · ".join(details))
    desc = (
        f'<div class="apg-card-desc">{html.escape(saved.description)}</div>'
        if saved.description
        else ""
    )
    link = safe_url(saved.url, TRACK_URL_PREFIX)
    button = (
        f'<a class="apg-open-spotify" href="{link}" target="_blank" '
        f'rel="noopener noreferrer">Open on Spotify</a>'
        if link
        else ""
    )
    return (
        f'<div class="apg-card apg-saved">{cover_html(saved)}<div class="apg-saved-body">'
        f'<div><span class="apg-chip">Saved to Spotify</span></div>'
        f'<div class="apg-saved-title">{html.escape(saved.title)}</div>{desc}'
        f'<div class="apg-card-meta">{meta}</div>'
        f'<div class="apg-saved-actions">{button}'
        f'<span class="apg-saved-logo">{spotify_logo_html()}</span></div></div></div>'
    )


def render_saved_card(saved: SavedPlaylist) -> None:
    """Render the saved card inside the current chat message.

    Args:
        saved: The saved-playlist snapshot.
    """
    st.markdown(saved_card_html(saved), unsafe_allow_html=True)
