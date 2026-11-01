"""Resolve LLM track suggestions to Spotify tracks: parallel search, matching and selection.

Searches are deduplicated within one call only. There is no module-level or cross-request
cache: Spotify's Developer Terms forbid caching content beyond immediate use, so the local
results dict is discarded when the call returns. The output is never passed back to the LLM.
"""

from collections import Counter
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from contextlib import closing
from typing import Any

from src.config import get_settings
from src.schema import ResolvedTrack, TrackSuggestion
from src.spotify import auth
from src.spotify.client import SpotifyBadRequestError, SpotifyClient
from src.spotify.matching import best_match, normalize, to_resolved

MAX_WORKERS = 5  # Parallel searches per call, bounded to respect Spotify's rate limits

SearchKey = tuple[str, str, str]  # Normalized (title, artist, market) of one search


def _search(
    client: SpotifyClient, token: str, suggestion: TrackSuggestion, market: str
) -> dict[str, Any] | None:
    """Search one suggestion and return its best match (runs in a worker thread).

    Args:
        client: Shared Spotify client (thread-safe).
        token: App access token.
        suggestion: The LLM's title/artist pair.
        market: Market code for the search.

    Returns:
        The matched `TrackObject`, or None when nothing matches.
    """
    try:
        items = client.search_tracks(token, suggestion.title, suggestion.artist, market)
    except SpotifyBadRequestError:
        return None  # One odd query must not sink the whole playlist; logged by the client
    return best_match(suggestion, items)


def _select(
    suggestions: list[TrackSuggestion],
    keys: list[SearchKey],
    matches: dict[SearchKey, dict[str, Any] | None],
    size: int,
) -> list[ResolvedTrack]:
    """Keep the first `size` found tracks in suggestion order, flagging not-found ones.

    Surplus found tracks are dropped, and so is a track already selected (same URI).

    Args:
        suggestions: The LLM's suggestions, in order.
        keys: Search key of each suggestion.
        matches: Best match per search key.
        size: Number of found tracks the playlist needs.

    Returns:
        Found tracks interleaved with flagged (found=False) entries for display.
    """
    selected: list[ResolvedTrack] = []
    seen_uris: set[str] = set()
    for suggestion, key in zip(suggestions, keys, strict=True):
        if len(seen_uris) >= size:
            break
        item = matches.get(key)
        if item is None:
            selected.append(
                ResolvedTrack(name=suggestion.title, artists=[suggestion.artist], found=False)
            )
        elif str(item.get("uri")) not in seen_uris:
            seen_uris.add(str(item.get("uri")))
            selected.append(to_resolved(item))
    return selected


def resolve_tracks(
    suggestions: list[TrackSuggestion],
    size: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[ResolvedTrack]:
    """Resolve suggestions on Spotify with the app token and select the playlist tracks.

    Args:
        suggestions: The LLM's candidates (over-generated), in order.
        size: Number of found tracks to keep (already clamped by the caller).
        on_progress: Callback (done, total), always invoked on the calling thread.

    Returns:
        Up to `size` found tracks plus flagged not-found entries, in suggestion order.
    """
    market = get_settings().spotify_market
    keys = [(normalize(s.title), normalize(s.artist), market) for s in suggestions]
    unique: dict[SearchKey, TrackSuggestion] = {}
    for key, suggestion in zip(keys, suggestions, strict=True):
        unique.setdefault(key, suggestion)  # The first suggestion's spelling is searched
    counts, total, done = Counter(keys), len(suggestions), 0
    matches: dict[SearchKey, dict[str, Any] | None] = {}
    if not unique:
        return []
    token = auth.get_app_token()
    with closing(SpotifyClient()) as client, ThreadPoolExecutor(MAX_WORKERS) as pool:
        futures: dict[Future[dict[str, Any] | None], SearchKey] = {
            pool.submit(_search, client, token, s, market): k for k, s in unique.items()
        }
        try:
            for future in as_completed(futures):
                key = futures[future]
                matches[key] = future.result()
                for _ in range(counts[key]):
                    done += 1
                    if on_progress:
                        on_progress(done, total)
        except BaseException:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
    return _select(suggestions, keys, matches, size)
