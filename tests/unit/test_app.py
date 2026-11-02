"""Unit tests for the app.py bootstrap, landing and session lifecycle (AppTest, all patched)."""

import pytest
from google.api_core.exceptions import ServiceUnavailable
from pytest_mock import MockerFixture

from src.ui import errors
from tests.unit.app_harness import Mocks, click, install_mocks, labels, run_app, texts
from tests.unit.session_factory import SID, make_state


@pytest.fixture
def mocks(mocker: MockerFixture) -> Mocks:
    """Patch every dependency of the app.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        The mocks, defaulting to a browser with no stored session.
    """
    return install_mocks(mocker)


def test_not_ready_shows_loader_only(mocks: Mocks) -> None:
    """Before the bridge answers, only the loader renders and Firestore is not read."""
    mocks.read.return_value = (False, None)
    at = run_app(mocks)
    assert not at.exception and labels(at) == [] and len(at.chat_input) == 0
    assert "Loading" in at.caption[0].value
    mocks.load.assert_not_called()


def test_no_session_shows_landing_with_exactly_two_buttons(mocks: Mocks) -> None:
    """Without a stored session the landing shows exactly the two entry points."""
    at = run_app(mocks)
    assert labels(at) == ["Continue with Spotify", "Use as a Guest"]
    assert "invite-only" in texts(at) and "personal data" in texts(at)
    mocks.load.assert_not_called()


def test_active_session_restores_chat(mocks: Mocks) -> None:
    """An active session restores its messages in the chat."""
    at = run_app(mocks, make_state(messages=3))
    mocks.load.assert_called_once_with(SID)
    assert len(at.chat_message) == 3 and len(at.chat_input) == 1
    assert "New chat" in labels(at)


def test_expired_session_shows_only_new_chat(mocks: Mocks) -> None:
    """An expired session shows the notice and only a New chat button."""
    mocks.read.return_value = (True, SID)
    mocks.load.return_value = ("expired", None)
    at = run_app(mocks)
    assert "expired" in at.info[0].value
    assert labels(at) == ["New chat"] and len(at.chat_input) == 0
    mocks.clear.assert_called_once()


def test_missing_session_clears_storage_and_shows_landing(mocks: Mocks) -> None:
    """A missing session clears localStorage and shows the landing."""
    mocks.read.return_value = (True, SID)
    at = run_app(mocks)
    mocks.clear.assert_called_once()
    assert "Use as a Guest" in labels(at)


def test_bootstrap_reads_firestore_once_per_session(mocks: Mocks) -> None:
    """Reruns reuse the cached bootstrap result (one Firestore read)."""
    run_app(mocks, make_state(messages=1)).run()
    assert mocks.load.call_count == 1 and mocks.read.call_count == 2


def test_guest_start_stores_session_id_and_shows_guest_badge(mocks: Mocks) -> None:
    """Use as a Guest creates the session, stores its id and shows the Guest badge."""
    at = click(run_app(mocks), "Use as a Guest")
    mocks.create.assert_called_once_with("guest")
    mocks.store.assert_called_once_with(SID)
    assert len(at.chat_input) == 1 and ":gray-badge[" in texts(at)
    assert "Guest]" in texts(at) and "Log in with Spotify" in labels(at)


def test_message_is_saved_and_new_chat_resets(mocks: Mocks) -> None:
    """A message is saved, and New chat deletes the session and returns to landing."""
    at = run_app(mocks, make_state())
    at.chat_input[0].set_value("Some 90s rock").run()
    assert mocks.save.call_args.args[1][0].content == "Some 90s rock"
    at = click(at, "New chat")
    mocks.delete.assert_called_once_with(SID)
    mocks.clear.assert_called_once()
    assert labels(at) == ["Continue with Spotify", "Use as a Guest"]


def test_message_on_expired_state_shows_expired_screen(mocks: Mocks) -> None:
    """A message on a session expired in an open tab shows the expired screen."""
    at = run_app(mocks, make_state())
    mocks.expired.return_value = True
    at.chat_input[0].set_value("hello").run()
    mocks.save.assert_not_called()
    mocks.run_turn.assert_not_called()
    mocks.delete.assert_called_once_with(SID)
    mocks.clear.assert_called_once()
    assert labels(at) == ["New chat"] and len(at.chat_input) == 0


def test_firestore_error_on_guest_start_shows_save_failed(mocks: Mocks) -> None:
    """A Firestore error on guest start is shown and no id is stored."""
    mocks.create.side_effect = ServiceUnavailable("down")  # type: ignore[no-untyped-call]
    at = click(run_app(mocks), "Use as a Guest")
    assert errors.SAVE_FAILED in texts(at)
    mocks.store.assert_not_called()
