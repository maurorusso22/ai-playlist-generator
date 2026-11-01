"""Live Gemma tests for the intent gate: clear off-topic is blocked, music always passes.

Requires a populated `.env` (the settings need all six required variables) and calls the
real Gemini API with the Gemma model, so the module is skipped when `GOOGLE_API_KEY` or the
settings are missing:

    pytest tests/integration/test_intent_gate_integration.py
"""

import logging
import os
import time
from collections.abc import Iterator

import pytest
from dotenv import load_dotenv

from src import intent_gate
from src.config import ConfigError, get_settings
from src.schema import ChatMessage

load_dotenv()

pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="Live Gemma tests require GOOGLE_API_KEY in .env",
)

ASKED_SIZE = [  # A conversation whose last reply asks a question, for short follow-ups
    ChatMessage(role="user", content="Chill lo-fi for studying"),
    ChatMessage(role="assistant", content="Nice! How many tracks would you like?"),
]

_logger = logging.getLogger(__name__)


@pytest.fixture(scope="module", autouse=True)
def live_settings() -> Iterator[None]:
    """Skip the module when the settings cannot be loaded from the environment.

    Returns:
        Nothing; yields once the settings are valid and clears the caches afterwards.
    """
    get_settings.cache_clear()
    intent_gate._build_gate.cache_clear()
    try:
        get_settings()
    except ConfigError as exc:
        pytest.skip(f"Live Gemma tests require a complete .env: {exc}")
    yield
    get_settings.cache_clear()
    intent_gate._build_gate.cache_clear()


def _gate(text: str, history: list[ChatMessage]) -> bool:
    """Run the live gate once, logging its latency.

    Args:
        text: The user message.
        history: Stored chat messages before it.

    Returns:
        True when the message is blocked.
    """
    started = time.perf_counter()
    blocked = intent_gate.gate_turn(text, history) is not None
    _logger.info("Gate %.2fs blocked=%s: %s", time.perf_counter() - started, blocked, text)
    return blocked


@pytest.mark.parametrize(
    "text",
    [
        "Write a Python function that reverses a linked list",
        "What's the capital of Australia?",
        "Give me a recipe for carbonara",
    ],
)
def test_clear_off_topic_is_blocked(text: str) -> None:
    """Messages with no link to music are blocked before Gemini."""
    assert _gate(text, []) is True


@pytest.mark.parametrize(
    "text",
    [
        "2010s house with Martin Garrix and Hardwell",
        "Fammi una playlist per correre",
        "something for a rainy sunday",
        "Hi! What can you do?",
        "Who produced Daft Punk's Discovery?",
        "I need to focus on my maths homework tonight",
        "Give me a carbonara recipe and some Italian dinner music",
    ],
)
def test_music_and_small_talk_pass(text: str) -> None:
    """Music requests in any language, small talk and music questions are never blocked."""
    assert _gate(text, []) is False


@pytest.mark.parametrize("text", ["30", "yes", "more upbeat please"])
def test_short_follow_ups_pass_in_context(text: str) -> None:
    """Short replies to the assistant's question pass thanks to the reply context."""
    assert _gate(text, ASKED_SIZE) is False
