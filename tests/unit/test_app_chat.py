"""Unit tests for chat turns: playlist card, confirmation buttons, non-blocking dismissal."""

import pytest
from pytest_mock import MockerFixture
from streamlit.testing.v1 import AppTest

from src.intent_gate import OUT_OF_SCOPE_REPLY
from src.schema import AssistantTurn, PlaylistCriteria
from tests.unit.app_builders import draft_state, make_tracks, propose_turn, session
from tests.unit.app_harness import Mocks, install_mocks, labels, run_app, texts
from tests.unit.session_factory import make_state


@pytest.fixture
def mocks(mocker: MockerFixture) -> Mocks:
    """Patch every dependency of the app.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        The mocks.
    """
    return install_mocks(mocker)


def _send(mocks: Mocks, mode: str, found: int, text: str = "2010s house hits") -> AppTest:
    """Send one message that the mocked LLM answers with a playlist of `found` tracks.

    Args:
        mocks: The installed mocks.
        mode: Session mode.
        found: Target size, all tracks found.
        text: The message.

    Returns:
        The AppTest after the turn.
    """
    mocks.run_turn.return_value = propose_turn(found)
    mocks.resolve.return_value = make_tracks(found)
    at = run_app(mocks, session(mode=mode))
    return at.chat_input[0].set_value(text).run()


def _rows(at: AppTest) -> int:
    """Count rendered track rows.

    Args:
        at: The AppTest after a run.

    Returns:
        Number of track row containers in the page.
    """
    return sum(str(m.value).count('class="apg-row') for m in at.markdown)


def test_propose_in_spotify_mode_renders_card_and_confirm_buttons(mocks: Mocks) -> None:
    """A 16-track proposal shows the card, the expander and the confirm buttons."""
    at = _send(mocks, "spotify", 16)
    assert [e.label for e in at.expander] == ["Show all 16 tracks"]
    assert _rows(at) == 16 and "House Hits" in texts(at)
    assert labels(at)[-2:] == ["Create on Spotify", "Not now"]
    draft = mocks.run_turn.return_value.playlist
    mocks.resolve.assert_called_once()
    assert mocks.resolve.call_args.args[:2] == (draft.tracks, 16)


def test_four_track_playlist_renders_no_expander(mocks: Mocks) -> None:
    """A playlist of at most 5 rows renders no expander."""
    at = _send(mocks, "spotify", 4)
    assert len(at.expander) == 0 and _rows(at) == 4


def test_propose_in_guest_mode_offers_only_login_to_save(mocks: Mocks) -> None:
    """Guests get only the login-to-save button under a proposal."""
    at = _send(mocks, "guest", 16)
    assert "Log in with Spotify to save" in labels(at)
    assert "Create on Spotify" not in labels(at) and "Not now" not in labels(at)


def test_new_message_dismisses_pending_buttons(mocks: Mocks) -> None:
    """A new message clears the pending action, so stale buttons disappear (FR-08)."""
    at = run_app(mocks, draft_state())
    assert "Create on Spotify" in labels(at)
    at.chat_input[0].set_value("Actually, make it rock").run()
    assert "Create on Spotify" not in labels(at) and "Not now" not in labels(at)
    assert at.session_state["session"].pending_action is None
    assert mocks.save.call_args.kwargs == {"pending_action": None}


def test_clarify_turn_renders_no_card_and_no_buttons(mocks: Mocks) -> None:
    """A clarification renders neither a card nor action buttons."""
    at = run_app(mocks, make_state())
    at.chat_input[0].set_value("Make me a playlist").run()
    assert _rows(at) == 0 and labels(at) == ["Log in with Spotify", "New chat"]
    assert "Which genre?" in texts(at)
    mocks.resolve.assert_not_called()


def test_history_sent_to_llm_excludes_the_new_message(mocks: Mocks) -> None:
    """The LLM gets the stored history without the new message and no draft."""
    state = make_state(messages=2)
    run_app(mocks, state).chat_input[0].set_value("more").run()
    text, history, draft = mocks.run_turn.call_args.args
    assert text == "more" and history == state.messages and draft is None


def test_gated_message_skips_gemini_and_saves_the_fixed_reply(mocks: Mocks) -> None:
    """A message the intent gate blocks gets the fixed reply, saved, without calling Gemini."""
    blocked = AssistantTurn(
        intent="off_topic", criteria=PlaylistCriteria(), message=OUT_OF_SCOPE_REPLY
    )
    mocks.gate.return_value = blocked
    state = make_state(messages=2)
    at = run_app(mocks, state).chat_input[0].set_value("Fix my Python code").run()
    assert mocks.gate.call_args.args == ("Fix my Python code", state.messages)
    mocks.run_turn.assert_not_called()
    mocks.resolve.assert_not_called()
    saved = mocks.save.call_args.args[1]
    assert [(m.role, m.content) for m in saved] == [
        ("user", "Fix my Python code"),
        ("assistant", OUT_OF_SCOPE_REPLY),
    ]
    assert OUT_OF_SCOPE_REPLY in texts(at)
