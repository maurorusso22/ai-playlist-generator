"""Unit tests for the Claude engine's web search: tool, rules and paused search loops."""

from datetime import date
from unittest.mock import MagicMock

import anthropic
import pytest

from src.config.files import Sections
from src.config.settings import get_settings
from src.conversation import chain
from src.llm import claude
from tests.unit.claude_fakes import CLARIFY, PAUSED_PARAM, claude_response


def test_search_tool_and_rules_are_sent(claude_client: MagicMock) -> None:
    """Search is on by default: direct capped calls, Spotify blocked, date and cap in the rules."""
    create = claude_client.return_value.messages.create
    create.return_value = claude_response(CLARIFY.model_dump_json(), searches=2)
    assert chain.run_turn("Latest Olivia Rodrigo album", [], None) == CLARIFY
    kwargs = create.call_args.kwargs
    assert kwargs["tools"] == [
        {
            "type": "web_search_20260318",
            "name": "web_search",
            "max_uses": 3,
            "blocked_domains": ["spotify.com", "scdn.co"],
            "allowed_callers": ["direct"],
        }
    ]
    assert f"today is {date.today().isoformat()}" in kwargs["system"]
    assert "at most 3 searches" in kwargs["system"]


def test_search_off_sends_no_tool_and_no_rules(claude_client: MagicMock, config: Sections) -> None:
    """With web_search = false the request has no tools and the prompt has no search rules."""
    config["claude"]["web_search"] = False
    get_settings.cache_clear()
    create = claude_client.return_value.messages.create
    create.return_value = claude_response(CLARIFY.model_dump_json())
    chain.run_turn("Hi", [], None)
    kwargs = create.call_args.kwargs
    assert kwargs["tools"] is anthropic.omit
    assert "Web search" not in kwargs["system"]


def test_paused_search_is_continued_with_the_paused_content(claude_client: MagicMock) -> None:
    """A pause_turn is resumed by sending the paused content back, with the same tools."""
    create = claude_client.return_value.messages.create
    paused = claude_response(stop_reason="pause_turn")
    create.side_effect = [paused, claude_response(CLARIFY.model_dump_json())]
    assert chain.run_turn("Latest Jack Harlow album", [], None) == CLARIFY
    first, second = (call.kwargs for call in create.call_args_list)
    assert second["messages"] == [*first["messages"], PAUSED_PARAM]
    assert second["tools"] == first["tools"]


def test_endless_pause_ends_unavailable(claude_client: MagicMock) -> None:
    """Continuations are capped: a reply still paused counts as unparsable, then unavailable."""
    create = claude_client.return_value.messages.create
    create.return_value = claude_response(stop_reason="pause_turn")
    with pytest.raises(chain.AssistantUnavailableError):
        chain.run_turn("Hi", [], None)
    assert create.call_count == chain.PARSE_ATTEMPTS * (claude.MAX_CONTINUATIONS + 1)


def test_reply_is_read_from_the_last_text_block(claude_client: MagicMock) -> None:
    """Text emitted before the search steps is ignored: the JSON reply comes last."""
    create = claude_client.return_value.messages.create
    create.return_value = claude_response("Searching", CLARIFY.model_dump_json(), searches=1)
    assert chain.run_turn("New single by Dua Lipa", [], None) == CLARIFY
    assert create.call_count == 1
