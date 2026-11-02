"""Unit tests for src/guards/intent_gate.py: fail-open out-of-scope gating with a mocked Gemma."""

import logging
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from google.genai.errors import ClientError
from langchain_core.messages import AIMessage, SystemMessage
from pytest_mock import MockerFixture

from src.guards import intent_gate
from src.models.session.chat_message import ChatMessage

HISTORY = [  # A notice after the assistant reply: it may hold Spotify data, so it is skipped
    ChatMessage(role="user", content="House music please"),
    ChatMessage(role="assistant", content="How many tracks would you like?"),
    ChatMessage(role="notice", content="Saved House Hits to Spotify"),
]


@pytest.fixture
def gemma(mocker: MockerFixture) -> Iterator[MagicMock]:
    """Patch the Gemma chat model; it answers IN unless a test says otherwise.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        The patched model class, yielded; the lazily built gate is cleared around each test.
    """
    intent_gate._build_gate.cache_clear()
    llm_cls = mocker.patch("src.guards.intent_gate.ChatGoogleGenerativeAI")
    llm_cls.return_value.invoke.return_value = AIMessage(content="IN")
    yield llm_cls
    intent_gate._build_gate.cache_clear()


def _answer(gemma: MagicMock, content: str | list[str | dict[str, str]]) -> None:
    """Make Gemma answer `content`.

    Args:
        gemma: The patched model class.
        content: The AIMessage content Gemma returns.
    """
    gemma.return_value.invoke.return_value = AIMessage(content=content)


def test_out_returns_the_fixed_off_topic_turn(gemma: MagicMock) -> None:
    """OUT blocks the message with a fixed off-topic turn and no playlist."""
    _answer(gemma, "OUT")
    turn = intent_gate.gate_turn("Write a Python sort function", HISTORY)
    assert turn is not None and turn.intent == "off_topic"
    assert turn.message == intent_gate.OUT_OF_SCOPE_REPLY and turn.playlist is None


@pytest.mark.parametrize("answer", ["OUT", "out.", " OUT\n", "**OUT**", "Out - coding"])
def test_any_spelling_of_out_blocks(gemma: MagicMock, answer: str) -> None:
    """Case, whitespace, markdown and trailing words around OUT still block."""
    _answer(gemma, answer)
    assert intent_gate.gate_turn("What is 2 + 2?", []) is not None


@pytest.mark.parametrize("answer", ["IN", "in", "", "Maybe", "OUTSIDE", "IN, not OUT"])
def test_anything_but_out_lets_the_message_through(gemma: MagicMock, answer: str) -> None:
    """IN, an empty answer or any other word fails open."""
    _answer(gemma, answer)
    assert intent_gate.gate_turn("yes", HISTORY) is None


def test_thinking_blocks_are_ignored(gemma: MagicMock) -> None:
    """Only the text part of a multi-part answer is classified."""
    _answer(gemma, [{"type": "thinking", "thinking": "IN?"}, {"type": "text", "text": "OUT"}])
    assert intent_gate.gate_turn("Solve x^2 = 4", []) is not None


@pytest.mark.parametrize(
    "error",
    [
        ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}),
        TimeoutError("deadline"),
        RuntimeError("boom"),
    ],
)
def test_failures_fail_open_and_are_logged(
    gemma: MagicMock, error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    """Quota errors, timeouts and anything else let the message through, with a warning."""
    gemma.return_value.invoke.side_effect = error
    with caplog.at_level(logging.WARNING, logger="src.guards.intent_gate"):
        assert intent_gate.gate_turn("Some techno", []) is None
    assert "failed open" in caplog.text


def test_unexpected_answer_is_logged(gemma: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    """An answer that is neither IN nor OUT is logged, so a broken gate is visible."""
    _answer(gemma, "Sure! Here is a playlist")
    with caplog.at_level(logging.WARNING, logger="src.guards.intent_gate"):
        assert intent_gate.gate_turn("Some techno", []) is None
    assert "unexpected answer" in caplog.text


def test_model_is_tuned_for_a_fast_one_word_answer(gemma: MagicMock) -> None:
    """Gemma is built from the settings with thinking off and a single short attempt."""
    intent_gate.gate_turn("Some techno", [])
    gemma.assert_called_once_with(
        model="gemma-4-26b-a4b-it",
        google_api_key="test-google-api-key",
        temperature=0,
        thinking_level="minimal",
        max_tokens=intent_gate.GATE_MAX_TOKENS,
        timeout=intent_gate.GATE_TIMEOUT_S,
        max_retries=1,
        additional_headers={"X-Server-Timeout": "10"},
    )


def test_prompt_holds_the_last_assistant_reply_but_no_notice(gemma: MagicMock) -> None:
    """The gate sees the rules, the last assistant reply and the message, never a notice."""
    intent_gate.gate_turn("30", HISTORY)
    system, human = gemma.return_value.invoke.call_args.args[0]
    assert isinstance(system, SystemMessage) and system.content == intent_gate.GATE_PROMPT
    assert "How many tracks would you like?" in human.content
    assert "<user_message>30</user_message>" in human.content
    assert "Saved House Hits" not in human.content


def test_context_is_the_tail_of_the_reply_or_none(gemma: MagicMock) -> None:
    """A long reply is cut to its tail; with no reply yet the context says (none)."""
    long_reply = "x" * 2000 + "Which era do you prefer?"
    intent_gate.gate_turn("80s", [ChatMessage(role="assistant", content=long_reply)])
    human = gemma.return_value.invoke.call_args.args[0][1]
    assert "Which era do you prefer?" in human.content and "x" * 1000 not in human.content
    intent_gate.gate_turn("hi", [])
    human = gemma.return_value.invoke.call_args.args[0][1]
    assert "<assistant_last_message>(none)</assistant_last_message>" in human.content


def test_long_messages_skip_the_gate(gemma: MagicMock) -> None:
    """A message too long to judge whole goes straight to Gemini."""
    _answer(gemma, "OUT")
    text = "a" * (intent_gate.MAX_GATED_CHARS + 1)
    assert intent_gate.gate_turn(text, []) is None
    gemma.return_value.invoke.assert_not_called()
