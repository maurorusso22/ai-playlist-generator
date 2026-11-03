"""Unit tests for src/spotify/resolver.py and its matching helpers (respx on GET /search)."""

import re
import threading
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from pytest_mock import MockerFixture

from src.models.conversation.track_suggestion import TrackSuggestion
from src.spotify.client import API_BASE_URL
from src.spotify.matching import normalize
from src.spotify.resolver import resolve_tracks

CATALOG: dict[str, list[dict[str, Any]]] = {}  # Search results by title, filled per test


def _item(name: str, artist: str, track_id: str | None = None) -> dict[str, Any]:
    """Build a TrackObject as returned by GET /search.

    Args:
        name: Track name.
        artist: Single artist name.
        track_id: Spotify id (defaults to the name).

    Returns:
        The track dict with album images of 640, 300 and 64 px.
    """
    track_id = track_id or name.replace(" ", "")
    images = [
        {"url": f"https://i.scdn.co/image/{w}", "width": w, "height": w} for w in (640, 300, 64)
    ]
    return {
        "id": track_id, "uri": f"spotify:track:{track_id}", "name": name,
        "artists": [{"name": artist}], "album": {"name": "Album", "images": images},
        "external_urls": {"spotify": f"https://open.spotify.com/track/{track_id}"},
        "duration_ms": 200000,
    }  # fmt: skip


def _search(request: httpx.Request) -> httpx.Response:
    """Answer GET /search from CATALOG using the `track:"..."` filter.

    Args:
        request: The intercepted search request.

    Returns:
        A search response with the catalog entries for that title.
    """
    match = re.search(r'track:"([^"]*)"', request.url.params["q"])
    title = match.group(1) if match else ""
    return httpx.Response(200, json={"tracks": {"items": CATALOG.get(title, [])}})


@pytest.fixture
def search(mocker: MockerFixture) -> Iterator[respx.Route]:
    """Patch the app token, mock GET /search from CATALOG and reset the catalog.

    Args:
        mocker: pytest-mock fixture.

    Returns:
        The search route, yielded to count calls.
    """
    mocker.patch("src.spotify.auth.get_app_token", return_value="app-token")
    CATALOG.clear()
    with respx.mock(base_url=API_BASE_URL) as router:
        yield router.get("/search").mock(side_effect=_search)


def _songs(count: int) -> list[TrackSuggestion]:
    """Build numbered suggestions "Song i" by "Artist i".

    Args:
        count: Number of suggestions.

    Returns:
        The suggestions, numbered from 1.
    """
    return [TrackSuggestion(title=f"Song {i}", artist=f"Artist {i}") for i in range(1, count + 1)]


def test_normalize_drops_versions_credits_and_accents() -> None:
    """Edits, remasters, featured artists, accents and punctuation do not affect matching."""
    assert normalize("Animals - Radio Edit") == "animals"
    assert normalize("Titanium (feat. Sia)") == "titanium"
    assert normalize("David Guetta feat. Sia") == "david guetta"
    assert normalize("Tiësto") == "tiesto"
    assert normalize("Wake Me Up!") == normalize("Wake Me Up")


def test_best_artist_match_wins(search: respx.Route) -> None:
    """The Martin Garrix edit beats the same title by Maroon 5; the 64 px image is chosen."""
    CATALOG["Animals"] = [
        _item("Animals", "Maroon 5", "m5"),
        _item("Animals - Radio Edit", "Martin Garrix", "mg"),
    ]
    [track] = resolve_tracks([TrackSuggestion(title="Animals", artist="Martin Garrix")], 1)
    assert (track.spotify_id, track.artists) == ("mg", ["Martin Garrix"])
    assert track.image_url == "https://i.scdn.co/image/64"


def test_unrelated_results_are_dropped(search: respx.Route) -> None:
    """A suggestion whose results all score below the threshold is left out."""
    CATALOG["Levels"] = [_item("Lean On", "Major Lazer"), _item("Levels", "Nick Jonas")]
    assert resolve_tracks([TrackSuggestion(title="Levels", artist="Avicii")], 1) == []


def test_over_generation_keeps_first_found_in_order(search: respx.Route) -> None:
    """20 candidates, #3 and #7 missing, size 16: the first 16 found, in order, nothing else."""
    CATALOG.update(
        {f"Song {i}": [_item(f"Song {i}", f"Artist {i}")] for i in range(1, 21) if i not in (3, 7)}
    )
    result = resolve_tracks(_songs(20), 16)
    assert [t.name for t in result] == [f"Song {i}" for i in range(1, 19) if i not in (3, 7)]


def test_dedup_within_call_but_no_cross_request_cache(search: respx.Route) -> None:
    """Identical suggestions share one search per call; a new call searches again."""
    CATALOG["Animals"] = [_item("Animals", "Martin Garrix")]
    suggestion = TrackSuggestion(title="Animals", artist="Martin Garrix")
    assert len(resolve_tracks([suggestion, suggestion], 2)) == 1  # Same URI kept once
    assert search.call_count == 1
    resolve_tracks([suggestion], 1)
    assert search.call_count == 2


def test_progress_reported_per_suggestion_on_calling_thread(search: respx.Route) -> None:
    """on_progress runs once per suggestion, in order, ending at (20, 20), never in a worker."""
    calls: list[tuple[int, int, int]] = []
    resolve_tracks(
        _songs(20), 16, lambda done, total: calls.append((done, total, threading.get_ident()))
    )
    assert [(done, total) for done, total, _ in calls] == [(i, 20) for i in range(1, 21)]
    assert {thread for _, _, thread in calls} == {threading.get_ident()}
