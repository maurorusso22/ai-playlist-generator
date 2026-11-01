"""Unit tests for failed chat turns: rate limit, Gemini and Spotify errors save nothing."""

import pytest
from google.genai.errors import ClientError
from pytest_mock import MockerFixture

from src.spotify.errors import SpotifyRateLimitError
from src.ui import errors
from tests.unit.app_builders import propose_turn
from tests.unit.app_harness import Mocks, install_mocks, run_app
from tests.unit.session_factory import make_state

DAILY_DETAILS = {  # Gemini 429 body whose exhausted quota is a per-day one
    "error": {
        "code": 429,
        "message": "You exceeded your current quota.",
        "status": "RESOURCE_EXHAUSTED",
        "details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}]}],
    }
}
MINUTE_DETAILS = {  # Gemini 429 body of a per-minute limit
    "error": {"code": 429, "message": "Rate limited.", "status": "RESOURCE_EXHAUSTED"}
}


@pytest.fixture
def mocks(mocker: MockerFixture) -> Mocks:
    """Patch every dependency of the app.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        The mocks.
    """
    return install_mocks(mocker)


def test_rate_limited_message_is_not_processed(mocks: Mocks) -> None:
    """A rate-limited message shows a warning and reaches neither the LLM nor Firestore."""
    mocks.limited.return_value = True
    at = run_app(mocks, make_state())
    at.chat_input[0].set_value("hello").run()
    assert errors.RATE_LIMITED in [w.value for w in at.warning]
    mocks.limited.assert_called_once_with("203.0.113.7")
    mocks.run_turn.assert_not_called()
    mocks.save.assert_not_called()


@pytest.mark.parametrize("body", [MINUTE_DETAILS, DAILY_DETAILS])
def test_gemini_429_is_mapped_and_nothing_saved(mocks: Mocks, body: dict[str, object]) -> None:
    """Every Gemini 429, per-minute or per-day, says to come back tomorrow and saves nothing."""
    mocks.run_turn.side_effect = ClientError(429, body)
    at = run_app(mocks, make_state())
    at.chat_input[0].set_value("hello").run()
    assert at.error[0].value == errors.DAILY_QUOTA
    mocks.save.assert_not_called()


def test_spotify_failure_while_resolving_saves_nothing(mocks: Mocks) -> None:
    """A Spotify failure during resolution shows the busy message and saves nothing."""
    mocks.run_turn.return_value = propose_turn(16)
    mocks.resolve.side_effect = SpotifyRateLimitError(429, "Too many requests")
    at = run_app(mocks, make_state())
    at.chat_input[0].set_value("house").run()
    assert errors.SPOTIFY_BUSY in at.error[0].value
    mocks.save.assert_not_called()
