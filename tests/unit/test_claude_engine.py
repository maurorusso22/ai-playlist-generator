"""Unit tests for the Claude engine behind `chain.run_turn`, with a mocked Anthropic SDK."""

from unittest.mock import MagicMock

import anthropic
import httpx2
import pytest

from src.config.errors import ConfigError
from src.config.secrets import get_secrets
from src.conversation import chain
from src.llm import claude
from src.models.session.chat_message import ChatMessage
from tests.unit.claude_fakes import CLARIFY, claude_response

HISTORY = [  # A notice may carry Spotify data: it must never reach the LLM
    ChatMessage(role="user", content="Hi"),
    ChatMessage(role="assistant", content="Hello!"),
    ChatMessage(role="notice", content="Saved: https://open.spotify.com/playlist/xyz"),
]


def test_turn_goes_to_claude_with_schema_effort_and_mapped_roles(claude_client: MagicMock) -> None:
    """The request carries the configured model, effort and cap, the schema and no notices."""
    create = claude_client.return_value.messages.create
    create.return_value = claude_response(CLARIFY.model_dump_json())
    assert chain.run_turn("Make it chill", HISTORY, None) == CLARIFY
    claude_client.assert_called_once_with(
        api_key="test-anthropic-api-key", max_retries=1, timeout=claude.CLAUDE_TIMEOUT_S
    )
    kwargs = create.call_args.kwargs
    assert (kwargs["model"], kwargs["max_tokens"]) == ("claude-haiku-5-5", 8192)
    assert kwargs["output_config"]["effort"] == "low"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    assert "between 1 and 30" in kwargs["system"]
    assert kwargs["messages"] == [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
        {"role": "user", "content": "Make it chill"},
    ]


def test_invalid_json_is_retried_once(claude_client: MagicMock) -> None:
    """A reply that fails validation counts as unparsable and is retried once."""
    create = claude_client.return_value.messages.create
    create.side_effect = [
        claude_response('{"intent": '),
        claude_response(CLARIFY.model_dump_json()),
    ]
    assert chain.run_turn("Hi", [], None) == CLARIFY
    assert create.call_count == 2


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_incomplete_replies_end_unavailable(claude_client: MagicMock, stop_reason: str) -> None:
    """A refusal or a reply cut by max_tokens is never parsed: two of them are unavailable."""
    create = claude_client.return_value.messages.create
    create.return_value = claude_response(CLARIFY.model_dump_json(), stop_reason=stop_reason)
    with pytest.raises(chain.AssistantUnavailableError):
        chain.run_turn("Hi", [], None)
    assert create.call_count == chain.PARSE_ATTEMPTS


def test_api_errors_propagate_without_chain_retry(claude_client: MagicMock) -> None:
    """SDK errors reach the UI unchanged; the SDK's own retry is the only one."""
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.RateLimitError(
        "slow down", response=httpx2.Response(429, request=request), body=None
    )
    create = claude_client.return_value.messages.create
    create.side_effect = error
    with pytest.raises(anthropic.RateLimitError):
        chain.run_turn("Hi", [], None)
    assert create.call_count == 1


def test_missing_api_key_is_a_config_error(
    claude_client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Selecting Claude without ANTHROPIC_API_KEY fails before any request."""
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    get_secrets.cache_clear()
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        chain.run_turn("Hi", [], None)
    claude_client.assert_not_called()
