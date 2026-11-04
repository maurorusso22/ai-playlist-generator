"""Unit tests for "Create on Spotify" / "Not now": idempotency, retries and error mapping."""

import pytest
from pytest_mock import MockerFixture

from src.models.session.created_playlist import CreatedPlaylist
from src.spotify.errors import (
    SpotifyAuthError,
    SpotifyBadRequestError,
    SpotifyForbiddenError,
    SpotifyRateLimitError,
)
from src.ui import errors
from tests.unit.app_builders import draft_state
from tests.unit.app_harness import PLAYLIST_ID, Mocks, click, install_mocks, labels, run_app, texts

PLAYLIST_URL = f"https://open.spotify.com/playlist/{PLAYLIST_ID}"  # Link the saved card must carry
TRACK_URIS = [f"spotify:track:id{i}" for i in range(14)]  # URIs of the 14 draft tracks


@pytest.fixture
def mocks(mocker: MockerFixture) -> Mocks:
    """Patch every dependency of the app.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        The mocks.
    """
    return install_mocks(mocker)


def test_create_calls_spotify_once_and_posts_the_saved_card(mocks: Mocks) -> None:
    """Create calls Spotify once with the draft's URIs and posts the saved-playlist card."""
    at = run_app(mocks, draft_state(tracks=14))
    at = click(at, "Create on Spotify")
    mocks.spotify.create_playlist.assert_called_once_with("access-1", "House Hits", "2010s house.")
    mocks.spotify.add_items.assert_called_once_with("access-1", PLAYLIST_ID, TRACK_URIS)
    state = at.session_state["session"]
    notice = state.messages[-1]
    assert notice.role == "notice" and notice.saved_playlist is not None
    assert notice.saved_playlist.url == PLAYLIST_URL and notice.saved_playlist.track_count == 14
    assert PLAYLIST_URL not in notice.content and "apg-saved" in texts(at)
    assert state.created_playlist.items_added and state.pending_action is None
    assert "Create on Spotify" not in labels(at) and "apg-confetti" in texts(at)
    at.run()
    assert mocks.spotify.create_playlist.call_count == 1
    assert mocks.spotify.add_items.call_count == 1


def test_add_items_rate_limit_keeps_buttons_and_retry_resumes(mocks: Mocks) -> None:
    """A failed add_items keeps the buttons; the retry never creates a second playlist."""
    mocks.spotify.add_items.side_effect = [SpotifyRateLimitError(429, "Slow down"), None]
    at = click(run_app(mocks, draft_state()), "Create on Spotify")
    assert errors.SPOTIFY_BUSY in [w.value for w in at.warning]
    assert "Create on Spotify" in labels(at)
    assert at.session_state["session"].created_playlist.id == PLAYLIST_ID
    at = click(at, "Create on Spotify")
    assert mocks.spotify.add_items.call_count == 2
    assert mocks.spotify.create_playlist.call_count == 1
    saved = at.session_state["session"].messages[-1].saved_playlist
    assert saved is not None and saved.url == PLAYLIST_URL


def test_already_created_playlist_is_not_created_again(mocks: Mocks) -> None:
    """A playlist already filled is shown again without any Spotify call."""
    created = CreatedPlaylist(id=PLAYLIST_ID, url=PLAYLIST_URL, items_added=True)
    at = click(run_app(mocks, draft_state(created_playlist=created)), "Create on Spotify")
    mocks.spotify.create_playlist.assert_not_called()
    mocks.spotify.add_items.assert_not_called()
    assert PLAYLIST_URL in at.info[0].value


def test_not_now_removes_buttons_without_spotify_call(mocks: Mocks) -> None:
    """Not now dismisses the buttons without calling Spotify."""
    at = click(run_app(mocks, draft_state()), "Not now")
    assert "Create on Spotify" not in labels(at) and "Not now" not in labels(at)
    assert mocks.touch.call_args.kwargs == {"pending_action": None}
    mocks.spotify.create_playlist.assert_not_called()


def test_401_refreshes_once_then_asks_to_log_in_again(mocks: Mocks) -> None:
    """A persistent 401 refreshes once, then switches back to the login button."""
    mocks.spotify.create_playlist.side_effect = SpotifyAuthError(401, "The access token expired")
    at = click(run_app(mocks, draft_state()), "Create on Spotify")
    mocks.refresh.assert_called_once()
    assert mocks.spotify.create_playlist.call_count == 2
    state = at.session_state["session"]
    assert state.mode == "guest" and state.spotify_auth is None
    assert state.messages[-1].content == errors.LOGIN_EXPIRED
    assert "Log in with Spotify to save" in labels(at)


def test_403_shows_invite_only_notice_and_drops_buttons(mocks: Mocks) -> None:
    """A 403 posts the invite-only notice and drops the buttons."""
    mocks.spotify.create_playlist.side_effect = SpotifyForbiddenError(403, "Forbidden")
    at = click(run_app(mocks, draft_state()), "Create on Spotify")
    state = at.session_state["session"]
    assert state.messages[-1].content == errors.INVITE_ONLY and state.mode == "guest"
    assert state.pending_action is None and "Create on Spotify" not in labels(at)


def test_400_shows_escaped_spotify_message_and_keeps_buttons(mocks: Mocks) -> None:
    """A 400 shows Spotify's escaped message and keeps the buttons."""
    error = SpotifyBadRequestError(400, "Invalid *name* [x](javascript:alert)")
    mocks.spotify.create_playlist.side_effect = error
    at = click(run_app(mocks, draft_state()), "Create on Spotify")
    warning = at.warning[0].value
    assert warning.startswith("Spotify couldn't complete the request:")
    assert r"\*name\*" in warning and r"\[x\]\(javascript\:alert\)" in warning
    assert "Create on Spotify" in labels(at)


def test_undecryptable_tokens_send_the_user_back_to_login(mocks: Mocks) -> None:
    """Tokens that cannot be decrypted lead to the login button, not to a call."""
    at = click(run_app(mocks, draft_state(spotify_auth="not-a-fernet-blob")), "Create on Spotify")
    mocks.spotify.create_playlist.assert_not_called()
    assert "Log in with Spotify to save" in labels(at)
