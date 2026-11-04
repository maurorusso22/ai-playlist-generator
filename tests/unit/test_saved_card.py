"""Unit tests for the saved-playlist card: snapshot, mosaic, escaping and URL allowlist."""

from src.models.session.saved_playlist import SavedPlaylist
from src.ui.saved_card import build_saved_playlist, format_duration, saved_card_html
from tests.unit.app_builders import make_draft, make_tracks

URL = "https://open.spotify.com/playlist/pl1"  # Link of the saved playlist
XSS = "<img src=x onerror=alert(1)>"  # Prompt-injected markup that must never render as HTML


def _saved(**fields: object) -> SavedPlaylist:
    """Build a saved playlist with overrides.

    Args:
        **fields: Field overrides.

    Returns:
        The snapshot.
    """
    base = SavedPlaylist(url=URL, title="House Hits", track_count=10, cover_urls=[])
    saved: SavedPlaylist = base.model_copy(update=fields)
    return saved


def test_snapshot_counts_only_added_tracks_and_builds_a_mosaic() -> None:
    """Tracks without a URI are skipped; four distinct covers make a mosaic."""
    tracks = make_tracks(6)
    tracks[0] = tracks[0].model_copy(update={"uri": None})
    tracks = [track.model_copy(update={"duration_ms": 180_000}) for track in tracks]
    saved = build_saved_playlist(make_draft(6), tracks, URL, "Mauro")
    assert saved.track_count == 5 and saved.duration_ms == 900_000 and saved.owner == "Mauro"
    assert saved.cover_urls == [f"https://i.scdn.co/image/{i}" for i in range(1, 5)]


def test_snapshot_falls_back_to_a_single_cover() -> None:
    """Fewer than four distinct covers keep only the first, like Spotify's own cover."""
    tracks = [
        t.model_copy(update={"image_url": "https://i.scdn.co/image/a"}) for t in make_tracks(5)
    ]
    tracks[1] = tracks[1].model_copy(update={"image_url": "https://evil.example/x.png"})
    saved = build_saved_playlist(make_draft(5), tracks, URL, None)
    assert saved.cover_urls == ["https://i.scdn.co/image/a"] and saved.duration_ms is None


def test_card_shows_details_and_open_button() -> None:
    """The card shows title, description, owner, count, duration and the Spotify link."""
    html = saved_card_html(_saved(description="2010s house.", owner="Mauro", duration_ms=2_520_000))
    assert "House Hits" in html and "2010s house." in html
    assert "by Mauro · 10 tracks · 42 min" in html and "Private" not in html
    assert f'href="{URL}"' in html and "Open on Spotify" in html


def test_mosaic_and_single_cover_sizes() -> None:
    """Four covers render as 64px tiles, one cover at full size, none as a placeholder."""
    covers = [f"https://i.scdn.co/image/{i}" for i in range(4)]
    assert saved_card_html(_saved(cover_urls=covers)).count('width="64"') == 4
    assert 'width="128"' in saved_card_html(_saved(cover_urls=covers[:1]))
    assert "apg-cover-empty" in saved_card_html(_saved())


def test_fields_are_escaped_and_foreign_urls_dropped() -> None:
    """Injected markup is escaped; links and images off Spotify's hosts are omitted."""
    html = saved_card_html(
        _saved(
            title=XSS,
            description=XSS,
            owner=XSS,
            url="javascript:alert(1)",
            cover_urls=["https://evil.example/x.png"],
        )
    )
    assert "<img src=x" not in html and "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "javascript:" not in html and "evil.example" not in html
    assert "Open on Spotify" not in html


def test_format_duration() -> None:
    """Durations round to minutes and switch to hours past sixty minutes."""
    assert format_duration(20_000) == "1 min"
    assert format_duration(2_520_000) == "42 min"
    assert format_duration(3_900_000) == "1 h 5 min"
