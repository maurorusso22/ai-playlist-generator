"""Unit tests for the playlist title: src/conversation/title.py, the guard and the prompt."""

import pytest

from src.conversation.chain import _system_prompt
from src.conversation.criteria import apply_guard
from src.conversation.title import FALLBACK_TITLE, MAX_TITLE_LENGTH, clean_title
from src.models.conversation.assistant_turn import AssistantTurn
from src.models.conversation.playlist_criteria import PlaylistCriteria
from src.models.conversation.playlist_draft import PlaylistDraft
from src.models.conversation.track_suggestion import TrackSuggestion


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Summer House Hits", "Summer House Hits"),
        ("  Summer\n House   Hits ", "Summer House Hits"),
        ('"Summer House Hits"', "Summer House Hits"),
        ("“Notti d'estate”", "Notti d'estate"),
        ("Rockin'", "Rockin'"),
    ],
)
def test_clean_title_normalizes(raw: str, expected: str) -> None:
    """Whitespace is collapsed and wrapping double quotes go; apostrophes stay."""
    assert clean_title(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", '""', "\n"])
def test_blank_title_gets_the_fallback(raw: str) -> None:
    """Spotify requires a name, so a blank title is never returned."""
    assert clean_title(raw) == FALLBACK_TITLE


def test_long_title_is_truncated_with_an_ellipsis() -> None:
    title = clean_title("Very long title " * 10)
    assert len(title) == MAX_TITLE_LENGTH
    assert title.endswith("…") and not title.endswith(" …")


def test_guard_cleans_the_draft_title() -> None:
    """apply_guard returns the cleaned title, leaving the input turn untouched."""
    draft = PlaylistDraft(
        title='  "Gym  Power" ',
        description="D",
        target_size=1,
        tracks=[TrackSuggestion(title="Titanium", artist="David Guetta")],
    )
    turn = AssistantTurn(
        intent="propose_playlist",
        criteria=PlaylistCriteria(moods=["gym"]),
        message="Here it is",
        playlist=draft,
    )
    guarded = apply_guard(turn, has_draft=False)
    assert guarded.playlist is not None
    assert guarded.playlist.title == "Gym Power"
    assert draft.title == '  "Gym  Power" '


def test_system_prompt_has_the_title_rule() -> None:
    """The prompt bounds the title length and covers user-given names and revisions."""
    prompt = _system_prompt(None)
    assert f"at most {MAX_TITLE_LENGTH} characters" in prompt
    assert "If the user names the playlist, use that name exactly" in prompt
    assert "keep the current title unless the user asks to rename it" in prompt
