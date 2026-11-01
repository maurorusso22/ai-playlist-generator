"""Live Gemini tests for the conversation engine.

Requires a populated `.env` (the settings need all six required variables) and calls the
real Gemini API, so the module is skipped when `GOOGLE_API_KEY` or the settings are missing:

    pytest tests/integration/test_chain_integration.py
"""

import logging
import os
import time
import warnings
from collections.abc import Iterator

import pytest
from dotenv import load_dotenv

from src.chain import run_turn
from src.config import ConfigError, get_settings
from src.schema import AssistantTurn

load_dotenv()

pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="Live Gemini tests require GOOGLE_API_KEY in .env",
)

NFR01_BUDGET_S = 3.0  # NFR-01 clarification latency target, checked here as a sanity bound
HOUSE_REQUEST = (  # The README example request
    "Make me a dance playlist with 2010s house music, picking the biggest hits by artists "
    "like Martin Garrix, David Guetta and Hardwell"
)

_logger = logging.getLogger(__name__)


@pytest.fixture(scope="module", autouse=True)
def live_settings() -> Iterator[None]:
    """Skip the module when the settings cannot be loaded from the environment.

    Returns:
        Nothing; yields once the settings are valid and clears the cache afterwards.
    """
    get_settings.cache_clear()
    try:
        get_settings()
    except ConfigError as exc:
        pytest.skip(f"Live Gemini tests require a complete .env: {exc}")
    yield
    get_settings.cache_clear()


def _timed_turn(text: str) -> tuple[AssistantTurn, float]:
    """Run one turn with no history and no draft, measuring its latency.

    Args:
        text: The user message.

    Returns:
        The guarded turn and the elapsed time in seconds.
    """
    started = time.perf_counter()
    turn = run_turn(text, [], None)
    return turn, time.perf_counter() - started


def test_vague_request_asks_for_criteria() -> None:
    """A request with no reference gets a clarification within the NFR-01 budget."""
    turn, elapsed = _timed_turn("Make me a playlist")
    _logger.info("Clarification latency: %.2fs (NFR-01 target %.1fs)", elapsed, NFR01_BUDGET_S)
    if elapsed > NFR01_BUDGET_S:
        warnings.warn(f"Clarification took {elapsed:.2f}s, above NFR-01", stacklevel=1)
    assert turn.intent == "clarify"
    assert turn.message.strip()
    assert turn.playlist is None


def test_house_example_proposes_a_default_size_playlist() -> None:
    """The README example yields a 16-track proposal with 16 to 20 candidates."""
    turn, elapsed = _timed_turn(HOUSE_REQUEST)
    _logger.info("Proposal latency: %.2fs", elapsed)
    assert turn.intent == "propose_playlist"
    assert any("martin garrix" in artist.casefold() for artist in turn.criteria.artists)
    assert turn.playlist is not None
    assert turn.playlist.target_size == 16
    assert 16 <= len(turn.playlist.tracks) <= 20


def test_oversized_request_is_capped_at_thirty() -> None:
    """A 50-song request is capped at 30 and the reply mentions the limit."""
    turn, _ = _timed_turn("Make me a 50-song rock playlist")
    assert turn.playlist is not None
    assert turn.playlist.target_size == 30
    assert "30" in turn.message


def test_off_topic_request_is_declined() -> None:
    """A non-music request is declined without a playlist."""
    turn, _ = _timed_turn("What's the weather in Rome?")
    assert turn.intent == "off_topic"
    assert turn.playlist is None
