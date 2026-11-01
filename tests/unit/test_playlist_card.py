"""Unit tests for the playlist card HTML: escaping, URL allowlist, not-found rows, artwork."""

import re

from src.schema import CreatedPlaylist, ResolvedTrack
from src.ui.playlist_card import attribution_html, card_header_html, safe_url, track_row_html
from tests.unit.app_builders import make_draft, make_tracks

XSS = "<img src=x onerror=alert(1)>"  # Prompt-injected markup that must never render as HTML


def _track(**fields: object) -> ResolvedTrack:
    """Build a found track with overrides.

    Args:
        **fields: Field overrides.

    Returns:
        The track.
    """
    track: ResolvedTrack = make_tracks(1)[0].model_copy(update=fields)
    return track


def test_title_and_artist_are_escaped() -> None:
    """Injected markup in track fields is escaped."""
    row = track_row_html(_track(name=XSS, artists=[XSS], album=f'"{XSS}'), 0)
    assert "&lt;img src=x onerror=alert(1)&gt;" in row
    assert "<img src=x" not in row and "onerror=alert(1)>" not in row


def test_external_url_outside_open_spotify_is_omitted() -> None:
    """A track link outside open.spotify.com is dropped."""
    row = track_row_html(_track(external_url="https://evil.example/track"), 0)
    assert "evil.example" not in row and "<a " not in row


def test_lookalike_hosts_and_schemes_are_rejected() -> None:
    """Lookalike hosts, javascript: URLs and missing URLs are rejected."""
    assert safe_url("https://open.spotify.com.evil.example/x", "https://open.spotify.com/") is None
    assert safe_url("javascript:alert(1)", "https://open.spotify.com/") is None
    assert safe_url(None, "https://i.scdn.co/") is None


def test_url_quotes_are_escaped_inside_attributes() -> None:
    """Quotes in an allowlisted URL cannot break out of the attribute."""
    row = track_row_html(_track(external_url='https://open.spotify.com/track/1" onmouseover="x'), 0)
    assert 'href="https://open.spotify.com/track/1&quot; onmouseover=&quot;x"' in row


def test_image_outside_spotify_cdn_is_omitted() -> None:
    """An image outside i.scdn.co is dropped."""
    row = track_row_html(_track(image_url="https://tracker.example/pixel.png"), 0)
    assert "tracker.example" not in row and "<img" not in row


def test_found_track_links_to_spotify_in_a_new_tab() -> None:
    """A found track links to Spotify in a new tab with its stagger index."""
    row = track_row_html(_track(), 3)
    assert 'href="https://open.spotify.com/track/id0"' in row and 'target="_blank"' in row
    assert 'rel="noopener noreferrer"' in row and 'style="--i:3"' in row


def test_not_found_track_has_badge_and_no_link() -> None:
    """A not-found track is dimmed, badged and unlinked (FR-16)."""
    track = ResolvedTrack(name="Lost", artists=["Nobody"], found=False)
    row = track_row_html(track, 0)
    assert "not found on Spotify" in row and "apg-missing" in row
    assert "<a " not in row and "<img" not in row


def test_not_found_track_never_links_even_with_a_url() -> None:
    """A not-found track is never linked, even if it carries a URL."""
    track = _track(found=False)
    assert "<a " not in track_row_html(track, 0)


def test_artwork_is_unaltered() -> None:
    """The cover image carries no style, class, filter or transform."""
    row = track_row_html(_track(), 0)
    img = re.search(r"<img[^>]*>", row)
    assert img is not None
    tag = img.group(0)
    assert 'src="https://i.scdn.co/image/0"' in tag and 'width="64" height="64"' in tag
    assert all(word not in tag for word in ("style", "class", "filter", "transform"))


def test_header_counts_found_and_missing_tracks() -> None:
    """The header shows the found and not-found counts."""
    header = card_header_html(make_draft(18), make_tracks(16, 2))
    assert "16 tracks · 2 not found on Spotify" in header and "House Hits" in header
    assert "not found" not in card_header_html(make_draft(4), make_tracks(4))


def test_header_escapes_llm_title_and_description() -> None:
    """The LLM title and description are escaped in the header."""
    draft = make_draft(1).model_copy(update={"title": XSS, "description": XSS})
    assert "<img src=x" not in card_header_html(draft, make_tracks(1))


def test_attribution_links_the_playlist_only_once_filled() -> None:
    """The attribution links the playlist only once its tracks are added."""
    url = "https://open.spotify.com/playlist/pl1"
    assert "Metadata provided by Spotify" in attribution_html(None)
    assert url not in attribution_html(CreatedPlaylist(id="pl1", url=url))
    assert url in attribution_html(CreatedPlaylist(id="pl1", url=url, items_added=True))
