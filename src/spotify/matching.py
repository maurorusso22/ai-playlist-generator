"""Matching of Spotify search results to LLM suggestions, and conversion of the match.

Plain Python only: Spotify data never reaches the LLM (Developer Policy).
"""

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from src.models.conversation.track_suggestion import TrackSuggestion
from src.models.spotify.resolved_track import ResolvedTrack

TITLE_WEIGHT = 0.6  # Share of the score from the title, weighted higher than the artist
ARTIST_WEIGHT = 0.4  # Share of the score from the best-matching artist
# Tuned on fixtures: a same-title track by another artist (e.g. "Animals" by Maroon 5 for
# Martin Garrix) scores about 0.79 and must be rejected; true matches score above 0.9.
MATCH_THRESHOLD = 0.85  # Minimum score for a candidate to count as found
BRACKETS_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]")  # Parenthesized/bracketed parts
DASH_SUFFIX_RE = re.compile(r"\s+-\s+.*$")  # " - Radio Edit", " - Remastered 2011", ...
FEAT_RE = re.compile(r"\s(feat|ft|featuring)\b\.?.*$")  # Trailing featured-artist credits
PUNCTUATION_RE = re.compile(r"[^\w\s]")  # Punctuation, so "Wake Me Up!" equals "Wake Me Up"
MIN_IMAGE_WIDTH = 64  # Smallest album image width (px) the playlist card can display


def normalize(text: str) -> str:
    """Normalize a title or artist name for comparison.

    Lowercases, strips accents (NFKD), drops bracketed parts, " - ..." suffixes, `feat.`
    credits and punctuation, and collapses whitespace.

    Args:
        text: Raw title or artist name.

    Returns:
        The normalized text, or the lowercased input when nothing would be left.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    cleaned = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    for pattern in (BRACKETS_RE, DASH_SUFFIX_RE, FEAT_RE, PUNCTUATION_RE):
        cleaned = pattern.sub("", cleaned)
    return " ".join(cleaned.split()) or text.lower().strip()


def _ratio(a: str, b: str) -> float:
    """Similarity of two normalized strings.

    Args:
        a: First normalized string.
        b: Second normalized string.

    Returns:
        SequenceMatcher ratio between 0 and 1.
    """
    return SequenceMatcher(None, a, b).ratio()


def score(suggestion: TrackSuggestion, item: dict[str, Any]) -> float:
    """Score how well a search result matches a suggestion.

    The artist part is the best ratio over the candidate's artists, also comparing all of
    them joined, so a suggestion like "Calvin Harris & Rihanna" matches a two-artist track.

    Args:
        suggestion: The LLM's title/artist pair.
        item: A `TrackObject` from GET /search.

    Returns:
        Weighted similarity between 0 and 1.
    """
    names = [normalize(a.get("name") or "") for a in item.get("artists") or []]
    artist = normalize(suggestion.artist)
    artist_ratio = max((_ratio(artist, n) for n in [*names, " ".join(names)]), default=0.0)
    title_ratio = _ratio(normalize(suggestion.title), normalize(item.get("name") or ""))
    return TITLE_WEIGHT * title_ratio + ARTIST_WEIGHT * artist_ratio


def best_match(suggestion: TrackSuggestion, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the best-scoring search result at or above MATCH_THRESHOLD.

    Ties keep Spotify's relevance order, so an original beats a same-named remix.

    Args:
        suggestion: The LLM's title/artist pair.
        items: `TrackObject` items from GET /search.

    Returns:
        The best matching item, or None when no item reaches the threshold.
    """
    best, best_score = None, 0.0
    for item in items:
        item_score = score(suggestion, item)
        if item_score > best_score:
            best, best_score = item, item_score
    return best if best_score >= MATCH_THRESHOLD else None


def pick_image(images: list[dict[str, Any]]) -> str | None:
    """Choose the smallest album image at least MIN_IMAGE_WIDTH pixels wide.

    Args:
        images: `ImageObject` list of the album (width may be null).

    Returns:
        The image URL, the first image when none qualifies, or None without images.
    """
    wide = [img for img in images if (img.get("width") or 0) >= MIN_IMAGE_WIDTH]
    if wide:
        return str(min(wide, key=lambda img: img["width"])["url"])
    return str(images[0]["url"]) if images else None


def to_resolved(item: dict[str, Any]) -> ResolvedTrack:
    """Convert a matched `TrackObject` into a ResolvedTrack.

    Args:
        item: The matched search result.

    Returns:
        A found ResolvedTrack with the Spotify fields filled.
    """
    album = item.get("album") or {}
    return ResolvedTrack(
        spotify_id=item.get("id"),
        uri=item.get("uri"),
        name=item.get("name") or "",
        artists=[a.get("name") or "" for a in item.get("artists") or []],
        album=album.get("name"),
        image_url=pick_image(album.get("images") or []),
        external_url=(item.get("external_urls") or {}).get("spotify"),
        duration_ms=item.get("duration_ms"),
        found=True,
    )
