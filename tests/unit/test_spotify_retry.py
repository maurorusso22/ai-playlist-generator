"""Unit tests for the Spotify retry policy (src/spotify/retry.py) through SpotifyClient."""

import logging
from collections.abc import Iterator
from unittest.mock import MagicMock, call

import httpx
import pytest
import respx
from pytest_mock import MockerFixture

from src.spotify.client import (
    API_BASE_URL,
    MAX_RETRIES,
    SpotifyClient,
    SpotifyForbiddenError,
    SpotifyQuotaError,
    SpotifyRateLimitError,
    SpotifyServerError,
)

TOKEN = "user-access-token"  # Fake bearer token; must never appear in logs
SEARCH_BODY = {"tracks": {"items": [{"uri": "spotify:track:t1"}]}}  # Minimal GET /search body


def _error(status: int, message: str = "boom", **extra: str) -> httpx.Response:
    """Build a Spotify ErrorObject response.

    Args:
        status: HTTP status code.
        message: Spotify's error.message.
        **extra: Extra ErrorObject fields (e.g. reason).

    Returns:
        The mocked response.
    """
    return httpx.Response(status, json={"error": {"status": status, "message": message, **extra}})


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    """Mock the Web API; unmocked requests fail the test.

    Returns:
        The respx router, yielded for route setup.
    """
    with respx.mock(base_url=API_BASE_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
def sleep(mocker: MockerFixture) -> MagicMock:
    """Patch time.sleep (no real waits) and remove the backoff jitter.

    Args:
        mocker: pytest-mock fixture.

    Returns:
        The sleep mock, to assert the waits.
    """
    mocker.patch("src.spotify.retry._jitter", return_value=0.0)
    sleep_mock: MagicMock = mocker.patch("src.spotify.retry.time.sleep")
    return sleep_mock


def test_429_honors_retry_after(api: respx.MockRouter, sleep: MagicMock) -> None:
    """A 429 with Retry-After waits exactly that long, then succeeds."""
    limited = httpx.Response(429, headers={"Retry-After": "2"}, json={})
    api.get("/search").mock(side_effect=[limited, httpx.Response(200, json=SEARCH_BODY)])
    assert SpotifyClient().search_tracks(TOKEN, "Animals", "Martin Garrix", "IT")
    sleep.assert_called_once_with(2)


def test_429_without_retry_after_backs_off_exponentially(
    api: respx.MockRouter, sleep: MagicMock
) -> None:
    """Two 429s without Retry-After wait 1 s then 2 s, never 0."""
    api.get("/search").mock(
        side_effect=[_error(429), _error(429), httpx.Response(200, json=SEARCH_BODY)]
    )
    SpotifyClient().search_tracks(TOKEN, "Animals", "Martin Garrix", "IT")
    assert sleep.call_args_list == [call(1.0), call(2.0)]


def test_429_every_attempt_raises_rate_limit(api: respx.MockRouter, sleep: MagicMock) -> None:
    """Retries are bounded by MAX_RETRIES, then SpotifyRateLimitError carries the message."""
    route = api.get("/search").mock(return_value=_error(429, "slow down"))
    with pytest.raises(SpotifyRateLimitError) as exc_info:
        SpotifyClient().search_tracks(TOKEN, "a", "b", "IT")
    assert route.call_count == MAX_RETRIES + 1
    assert sleep.call_count == MAX_RETRIES
    assert exc_info.value.message == "slow down"


def test_retry_after_too_long_fails_fast(api: respx.MockRouter, sleep: MagicMock) -> None:
    """A Retry-After beyond the cap is not waited for."""
    api.get("/search").respond(429, headers={"Retry-After": "3600"}, json={})
    with pytest.raises(SpotifyRateLimitError):
        SpotifyClient().search_tracks(TOKEN, "a", "b", "IT")
    sleep.assert_not_called()


def test_quota_exceeded_is_not_retried(api: respx.MockRouter, sleep: MagicMock) -> None:
    """reason QUOTA_EXCEEDED raises SpotifyQuotaError at once."""
    route = api.get("/search").mock(return_value=_error(429, "quota", reason="QUOTA_EXCEEDED"))
    with pytest.raises(SpotifyQuotaError):
        SpotifyClient().search_tracks(TOKEN, "a", "b", "IT")
    assert route.call_count == 1
    sleep.assert_not_called()


def test_5xx_then_success(api: respx.MockRouter, sleep: MagicMock) -> None:
    """Two 503s back off, then the third attempt succeeds."""
    api.get("/search").mock(
        side_effect=[_error(503), _error(503), httpx.Response(200, json=SEARCH_BODY)]
    )
    assert SpotifyClient().search_tracks(TOKEN, "a", "b", "IT")
    assert sleep.call_args_list == [call(1.0), call(2.0)]


def test_5xx_every_attempt_raises_server_error(api: respx.MockRouter, sleep: MagicMock) -> None:
    """Persistent 5xx ends with SpotifyServerError after bounded retries."""
    route = api.post("/me/playlists").mock(return_value=_error(502, "bad gateway"))
    with pytest.raises(SpotifyServerError) as exc_info:
        SpotifyClient().create_playlist(TOKEN, "Mix", "Desc")
    assert route.call_count == MAX_RETRIES + 1
    assert exc_info.value.status == 502


def test_connection_error_retried_for_get_only(api: respx.MockRouter, sleep: MagicMock) -> None:
    """A GET survives a dropped connection; a POST is never repeated blindly."""
    api.get("/me").mock(side_effect=[httpx.ConnectError("down"), httpx.Response(200, json={})])
    assert SpotifyClient().get_me(TOKEN) == {}
    route = api.post("/me/playlists").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(SpotifyServerError):
        SpotifyClient().create_playlist(TOKEN, "Mix", "Desc")
    assert route.call_count == 1


def test_errors_are_logged_without_token(
    api: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    """The status and error.message are logged; the Authorization header never is."""
    api.get("/me").mock(return_value=_error(403, "user not registered"))
    with caplog.at_level(logging.WARNING), pytest.raises(SpotifyForbiddenError):
        SpotifyClient().get_me(TOKEN)
    assert "403" in caplog.text
    assert "user not registered" in caplog.text
    assert TOKEN not in caplog.text
