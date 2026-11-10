"""Deterministic checks on the tracks of a draft: artists, titles, years and revisions.

Every check reads only the LLM's own output (title/artist/year it generated), never
Spotify data. Titles use the resolver's normalization (which drops "feat." and "- Remastered"
suffixes); artist credits keep featured artists, so "Calvin Harris feat. Rihanna" credits both.
"""

import unicodedata

from src.models.conversation.playlist_draft import PlaylistDraft
from src.models.conversation.track_suggestion import TrackSuggestion
from src.spotify.matching import PUNCTUATION_RE, normalize
from tests.evals.harness.cases import Expect


def _credits(text: str) -> str:
    """Fold an artist credit for word-level matching, keeping featured artists.

    Args:
        text: Artist name or credit.

    Returns:
        Casefolded, accent- and punctuation-free words, padded with spaces.
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return f" {' '.join(PUNCTUATION_RE.sub(' ', plain).split())} "


def _by(track: TrackSuggestion, artist: str) -> bool:
    """Tell whether a track credits an artist, as whole words ("Queen" is not "Queens").

    Args:
        track: The LLM's suggestion.
        artist: Artist name from the case.

    Returns:
        True when the artist's words appear in the track's artist credit.
    """
    return _credits(artist) in _credits(track.artist)


def _key(track: TrackSuggestion) -> tuple[str, str]:
    """Identity of a suggestion across two drafts.

    Args:
        track: The LLM's suggestion.

    Returns:
        Normalized title and artist.
    """
    return normalize(track.title), normalize(track.artist)


def _dropped_on_purpose(track: TrackSuggestion, expect: Expect) -> bool:
    """Tell whether the case asked to remove this previous track.

    Args:
        track: A track of the previous draft.
        expect: The case's expectations.

    Returns:
        True for a track by an excluded artist or with an excluded title.
    """
    by_excluded = any(_by(track, name) for name in expect.excludes_artists)
    titled = any(normalize(title) == normalize(track.title) for title in expect.excludes_titles)
    return by_excluded or titled


def track_checks(
    playlist: PlaylistDraft | None, previous: PlaylistDraft | None, expect: Expect
) -> dict[str, bool]:
    """Run the track expectations of a case; a missing playlist fails every one of them.

    Args:
        playlist: The final draft, or None.
        previous: The draft before the final turn, or None.
        expect: The case's expectations.

    Returns:
        Check name → passed, only for the expectations the case sets.
    """
    tracks = playlist.tracks if playlist is not None else []
    has = playlist is not None
    checks: dict[str, bool] = {}
    if expect.includes_artists:
        checks["includes_artists"] = has and all(
            any(_by(t, name) for t in tracks) for name in expect.includes_artists
        )
    if expect.excludes_artists:
        checks["excludes_artists"] = has and not any(
            _by(t, name) for t in tracks for name in expect.excludes_artists
        )
    if expect.only_artists:
        checks["only_artists"] = has and all(
            any(_by(t, name) for name in expect.only_artists) for t in tracks
        )
    if expect.excludes_titles:
        banned = {normalize(title) for title in expect.excludes_titles}
        checks["excludes_titles"] = has and not any(normalize(t.title) in banned for t in tracks)
    if expect.year_range is not None:
        low, high = expect.year_range
        checks["year_range"] = has and all(low <= t.year <= high for t in tracks if t.year)
    if expect.keeps_previous is not None:
        kept_before = [
            t for t in (previous.tracks if previous else []) if not _dropped_on_purpose(t, expect)
        ]
        now = {_key(t) for t in tracks}
        share = sum(_key(t) in now for t in kept_before) / len(kept_before) if kept_before else 0
        checks["keeps_previous"] = has and share >= expect.keeps_previous
    return checks
