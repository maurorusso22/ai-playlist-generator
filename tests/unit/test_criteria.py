"""Unit tests for the minimum-criteria guard and the playlist-size rules (offline)."""

from typing import Literal

import pytest

from src.config import get_settings
from src.criteria import apply_guard, candidate_count, clamp_size, has_minimum_criteria
from src.prompt import CLARIFICATION_FALLBACK
from src.schema import AssistantTurn, PlaylistCriteria, PlaylistDraft, TrackSuggestion

HOUSE = PlaylistCriteria(genres=["house"])  # Minimal criteria that satisfy the guard
Intent = Literal["clarify", "propose_playlist", "revise_playlist", "off_topic"]  # Turn intents
CLAMP_CASES = [(0, 1), (1, 1), (30, 30), (45, 30), (None, 16)]  # (requested, expected) sizes
NOT_ENOUGH = [  # Criteria that must fail the guard: empty, other constraints only, blank values
    PlaylistCriteria(),
    PlaylistCriteria(other_constraints=["danceable"]),
    PlaylistCriteria(genres=["  "], artists=[""]),
]


def _tracks(count: int) -> list[TrackSuggestion]:
    """Build distinct track suggestions.

    Args:
        count: Number of tracks.

    Returns:
        Suggestions "Song i" by "Artist i".
    """
    return [TrackSuggestion(title=f"Song {i}", artist=f"Artist {i}") for i in range(count)]


def _turn(
    intent: Intent,
    criteria: PlaylistCriteria | None = None,
    tracks: list[TrackSuggestion] | None = None,
    target_size: int = 16,
) -> AssistantTurn:
    """Build a canned LLM turn with the message "LLM message".

    Args:
        intent: Turn intent.
        criteria: Extracted criteria, empty by default.
        tracks: Draft tracks; no playlist when None.
        target_size: Size requested in the draft.

    Returns:
        The canned turn.
    """
    playlist = None
    if tracks is not None:
        playlist = PlaylistDraft(title="M", description="D", target_size=target_size, tracks=tracks)
    criteria = criteria or PlaylistCriteria()
    return AssistantTurn(intent=intent, criteria=criteria, message="LLM message", playlist=playlist)


@pytest.mark.parametrize("criteria", NOT_ENOUGH)
def test_missing_references_are_not_enough(criteria: PlaylistCriteria) -> None:
    """Empty, blank or other_constraints-only criteria fail the guard."""
    assert has_minimum_criteria(criteria) is False


@pytest.mark.parametrize("field", ["genres", "moods", "years", "artists", "albums", "songs"])
def test_any_single_reference_is_enough(field: str) -> None:
    """One non-empty value in any of the six lists passes the guard."""
    assert has_minimum_criteria(PlaylistCriteria(**{field: ["value"]})) is True


@pytest.mark.parametrize(("requested", "expected"), CLAMP_CASES)
def test_clamp_size(requested: int | None, expected: int) -> None:
    """Sizes are clamped to [1, 30] and default to 16."""
    assert clamp_size(requested) == expected


def test_clamp_size_honors_a_lower_configured_max(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLAYLIST_MAX_SIZE lowers the cap."""
    monkeypatch.setenv("PLAYLIST_MAX_SIZE", "20")
    get_settings.cache_clear()
    assert clamp_size(45) == 20


@pytest.mark.parametrize(("size", "expected"), [(16, 20), (30, 36), (1, 2), (5, 6), (15, 18)])
def test_candidate_count(size: int, expected: int) -> None:
    """Over-generation adds ceil(20%) candidates."""
    assert candidate_count(size) == expected


def test_oversized_target_is_clamped_and_truncated() -> None:
    """target_size=50 becomes 30 with at most 36 tracks; the input turn is left untouched."""
    turn = _turn("propose_playlist", HOUSE, _tracks(50), 50)
    guarded = apply_guard(turn, has_draft=False)
    assert guarded.playlist is not None and turn.playlist is not None
    assert guarded.playlist.target_size == 30
    assert len(guarded.playlist.tracks) <= 36
    assert (turn.playlist.target_size, len(turn.playlist.tracks)) == (50, 50)


def test_proposal_without_criteria_or_draft_becomes_fallback_clarification() -> None:
    """No criterion and no draft: deterministic clarification, no playlist."""
    guarded = apply_guard(_turn("propose_playlist", tracks=_tracks(20)), has_draft=False)
    assert guarded.intent == "clarify"
    assert guarded.message == CLARIFICATION_FALLBACK
    assert guarded.playlist is None


def test_revision_without_criteria_is_kept_when_a_draft_exists() -> None:
    """'Make it 30 songs' revises the existing draft even with empty criteria."""
    guarded = apply_guard(_turn("revise_playlist", tracks=_tracks(36), target_size=30), True)
    assert guarded.intent == "revise_playlist"
    assert guarded.playlist is not None
    assert (guarded.playlist.target_size, len(guarded.playlist.tracks)) == (30, 36)


def test_duplicate_and_blank_tracks_are_removed() -> None:
    """Duplicates differing only in case, accents or spacing are dropped, as are blanks."""
    pairs = [("Animals", "Martin Garrix"), ("  animals ", "MARTIN  GARRIX"), (" ", "Nobody")]
    pairs += [("Titanium", "David Guetta"), ("Titanium", "David Guétta"), ("Spaceman", "Hardwell")]
    tracks = [TrackSuggestion(title=title, artist=artist) for title, artist in pairs]
    guarded = apply_guard(_turn("propose_playlist", HOUSE, tracks), has_draft=False)
    assert guarded.playlist is not None
    assert [t.title for t in guarded.playlist.tracks] == ["Animals", "Titanium", "Spaceman"]


def test_extra_tracks_are_truncated_to_the_candidate_count() -> None:
    """40 tracks for a 16-track playlist are cut to the first 20."""
    guarded = apply_guard(_turn("propose_playlist", HOUSE, _tracks(40)), has_draft=False)
    assert guarded.playlist is not None
    assert guarded.playlist.tracks == _tracks(20)


@pytest.mark.parametrize("tracks", [None, [TrackSuggestion(title=" ", artist="Nobody")]])
def test_playlist_intent_without_usable_playlist_becomes_clarify(
    tracks: list[TrackSuggestion] | None,
) -> None:
    """A missing or empty playlist turns into a clarification keeping the LLM message."""
    guarded = apply_guard(_turn("propose_playlist", HOUSE, tracks), has_draft=False)
    assert (guarded.intent, guarded.message, guarded.playlist) == ("clarify", "LLM message", None)


@pytest.mark.parametrize("intent", ["clarify", "off_topic"])
def test_non_playlist_intents_drop_the_playlist(intent: Intent) -> None:
    """clarify/off_topic never carry a playlist."""
    guarded = apply_guard(_turn(intent, HOUSE, _tracks(20)), has_draft=True)
    assert (guarded.intent, guarded.message, guarded.playlist) == (intent, "LLM message", None)
