"""Configuration sections of the language models: the chat engine and the intent gate."""

from typing import Literal

from pydantic import PositiveInt

from src.config.sections import Section, Text

Provider = Literal["gemini", "claude"]  # Conversation engines selectable with llm.provider
Effort = Literal["low", "medium", "high", "xhigh", "max"]  # Claude output_config.effort levels


class LlmConfig(Section):
    """[llm]: the engine that answers the chat; the gate always runs on Google AI Studio."""

    provider: Provider


class ModelConfig(Section):
    """[gemini] and [intent_gate]: a Google AI Studio model id."""

    model: Text


class ClaudeConfig(Section):
    """[claude]: the Claude conversation engine, called through the Anthropic SDK."""

    model: Text
    effort: Effort
    max_tokens: PositiveInt
    web_search: bool
    max_searches: PositiveInt
