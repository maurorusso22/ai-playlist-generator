"""Claude conversation engine: one structured Messages API call through the Anthropic SDK.

The chain's LangChain messages are mapped to the Messages API shape (system prompt apart,
user/assistant turns in order). `output_config.format` constrains the reply to the
`AssistantTurn` JSON schema; thinking stays adaptive (the model default) and its depth is set
by [claude].effort, the setting that trades reply quality against token spend.
"""

import logging
from functools import lru_cache

import anthropic
from anthropic.types import MessageParam
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from src.config.errors import ConfigError
from src.config.secrets import get_secrets
from src.config.settings import get_settings
from src.models.conversation.assistant_turn import AssistantTurn

CLAUDE_MAX_RETRIES = 1  # One SDK retry on 408/409/429/5xx, honouring retry-after
CLAUDE_TIMEOUT_S = 60.0  # Per-request timeout: the SDK default of 10 minutes would freeze the chat

_logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    """Build the Anthropic client once, lazily, from ANTHROPIC_API_KEY.

    Returns:
        The client.
    """
    api_key = get_secrets().anthropic_api_key
    if not api_key:
        raise ConfigError("Missing ANTHROPIC_API_KEY in .env, required by llm.provider = claude")
    return anthropic.Anthropic(
        api_key=api_key, max_retries=CLAUDE_MAX_RETRIES, timeout=CLAUDE_TIMEOUT_S
    )


@lru_cache(maxsize=1)
def _output_schema() -> dict[str, object]:
    """Convert `AssistantTurn` to the JSON schema subset structured outputs accept, once.

    Returns:
        The schema for `output_config.format`.
    """
    return anthropic.transform_schema(AssistantTurn)


def _split(messages: list[BaseMessage]) -> tuple[str, list[MessageParam]]:
    """Separate the system prompt from the user/assistant turns.

    Args:
        messages: System, history and new user messages, as built by the chain.

    Returns:
        The system prompt and the turns in Messages API shape.
    """
    system = "\n\n".join(m.text for m in messages if isinstance(m, SystemMessage))
    turns: list[MessageParam] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            turns.append({"role": "user", "content": message.text})
        elif not isinstance(message, SystemMessage):
            turns.append({"role": "assistant", "content": message.text})
    return system, turns


def invoke(messages: list[BaseMessage]) -> AssistantTurn:
    """Call Claude once with the `AssistantTurn` output schema.

    A refusal, a reply cut by max_tokens or one failing validation raises
    `OutputParserException`, which the chain retries once; API errors propagate unchanged.

    Args:
        messages: System, history and new user messages.

    Returns:
        The parsed reply.
    """
    config = get_settings().claude
    system, turns = _split(messages)
    response = _client().messages.create(
        model=config.model,
        max_tokens=config.max_tokens,
        system=system,
        messages=turns,
        output_config={
            "effort": config.effort,
            "format": {"type": "json_schema", "schema": _output_schema()},
        },
    )
    if response.stop_reason != "end_turn":
        details = response.stop_details.category if response.stop_details else None
        _logger.warning("Claude stopped with %s (%s)", response.stop_reason, details)
        raise OutputParserException(f"Claude stopped with {response.stop_reason}")
    text = next((block.text for block in response.content if block.type == "text"), "")
    try:
        return AssistantTurn.model_validate_json(text)
    except ValidationError as exc:
        raise OutputParserException(f"Claude reply failed validation: {exc}") from exc
