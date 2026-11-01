"""Unit tests for the Spotify login: redirect after read-back and the OAuth callback."""

import pytest
from pytest_mock import MockerFixture

from src import crypto
from src.spotify.errors import SpotifyForbiddenError
from src.ui import errors
from tests.unit.app_builders import draft_state, session
from tests.unit.app_harness import OAUTH_STATE, Mocks, click, install_mocks, labels, run_app, texts
from tests.unit.session_factory import SID

CALLBACK = {"code": "auth-code", "state": "expected-state"}  # Query string of a valid callback


@pytest.fixture
def mocks(mocker: MockerFixture) -> Mocks:
    """Patch every dependency of the app.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        The mocks.
    """
    return install_mocks(mocker)


def test_login_redirects_only_after_the_session_id_is_read_back(mocks: Mocks) -> None:
    """The Spotify redirect waits until the browser reads back the stored id."""
    at = click(run_app(mocks), "Continue with Spotify")
    mocks.create.assert_called_once_with("guest")
    assert mocks.touch.call_args.kwargs == {"oauth_state": OAUTH_STATE}
    mocks.store.assert_called_once_with(SID)
    mocks.redirect.assert_not_called()
    mocks.read.return_value = (True, SID)
    at.run()
    url = mocks.redirect.call_args.args[0]
    assert url.startswith("https://accounts.spotify.com/authorize?")
    assert f"state={OAUTH_STATE}" in url and "scope=playlist-modify-private" in url


def test_login_gives_up_when_browser_storage_is_blocked(mocks: Mocks) -> None:
    """Blocked storage stops the login after bounded write attempts."""
    at = click(run_app(mocks), "Continue with Spotify")
    for _ in range(3):
        at.run()
    assert mocks.store.call_count == 3
    mocks.redirect.assert_not_called()
    assert errors.STORAGE_BLOCKED in texts(at)


def test_mismatched_state_is_rejected_without_code_exchange(mocks: Mocks) -> None:
    """A mismatched OAuth state is rejected before any code exchange."""
    state = session(oauth_state="other-state")
    at = run_app(mocks, state, CALLBACK)
    mocks.exchange.assert_not_called()
    assert errors.LOGIN_CHECK_FAILED in at.error[0].value
    assert at.session_state["session"].mode == "guest"


def test_valid_callback_logs_in_and_offers_the_pending_draft(mocks: Mocks) -> None:
    """A valid callback logs in, clears the URL and offers the pending draft (FR-07)."""
    state = draft_state(mode="guest", oauth_state="expected-state")
    at = run_app(mocks, state, CALLBACK)
    mocks.exchange.assert_called_once_with("auth-code")
    mocks.spotify.get_me.assert_called_once_with("access-1")
    saved = at.session_state["session"]
    assert saved.mode == "spotify" and saved.oauth_state is None
    tokens = crypto.decrypt_tokens(saved.spotify_auth)
    assert tokens is not None and tokens.display_name == "Mauro"
    assert dict(at.query_params) == {}
    assert saved.messages[-1].content == "You're logged in as Mauro — save 'House Hits' to Spotify?"
    assert labels(at)[-2:] == ["Create on Spotify", "Not now"]
    assert "Spotify · Mauro]" in texts(at)


def test_me_403_shows_invite_only_and_stays_guest(mocks: Mocks) -> None:
    """A 403 on /me keeps guest mode, stores no token and drops login_to_save."""
    mocks.spotify.get_me.side_effect = SpotifyForbiddenError(403, "User not registered")
    state = draft_state(mode="guest", oauth_state="expected-state")
    at = run_app(mocks, state, CALLBACK)
    saved = at.session_state["session"]
    assert saved.mode == "guest" and saved.spotify_auth is None
    assert saved.messages[-1].content == errors.INVITE_ONLY and saved.pending_action is None
    assert "Log in with Spotify to save" not in labels(at)


def test_denied_consent_shows_cancelled_notice(mocks: Mocks) -> None:
    """Denied consent posts the cancelled notice without an exchange."""
    at = run_app(mocks, session(oauth_state="expected-state"), {"error": "access_denied"})
    mocks.exchange.assert_not_called()
    assert at.session_state["session"].messages[-1].content == errors.LOGIN_CANCELLED


def test_callback_without_a_session_returns_to_landing(mocks: Mocks) -> None:
    """A callback without a session returns to the landing with a notice."""
    at = run_app(mocks, None, CALLBACK)
    mocks.exchange.assert_not_called()
    assert errors.LOGIN_TOO_SLOW in at.warning[0].value
    assert labels(at) == ["Continue with Spotify", "Use as a Guest"]


def test_callback_is_processed_once_per_session(mocks: Mocks) -> None:
    """A rerun does not process the same callback twice."""
    at = run_app(mocks, session(oauth_state="expected-state"), CALLBACK)
    at.run()
    mocks.exchange.assert_called_once()
