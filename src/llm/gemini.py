"""Gemini conversation engine: structured output through langchain-google-genai."""

from functools import lru_cache

from google.genai.errors import ClientError
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError

from src.config.secrets import get_secrets
from src.config.settings import get_settings
from src.models.conversation.assistant_turn import AssistantTurn

GEMINI_MAX_RETRIES = 2  # Total SDK attempts (1 retry): the default 6 delays 429 feedback by ~30 s


@lru_cache(maxsize=1)
def _build_llm() -> Runnable[list[BaseMessage], object]:
    """Build the Gemini model bound to the `AssistantTurn` schema, once and lazily.

    Returns:
        A runnable whose `invoke` returns a parsed `AssistantTurn`.
    """
    llm = ChatGoogleGenerativeAI(
        model=get_settings().gemini.model,
        google_api_key=get_secrets().google_api_key,
        max_retries=GEMINI_MAX_RETRIES,
    )
    structured: Runnable[list[BaseMessage], object] = llm.with_structured_output(AssistantTurn)
    return structured


def invoke(messages: list[BaseMessage]) -> AssistantTurn:
    """Call Gemini once, surfacing its client errors as `google.genai.errors.ClientError`.

    langchain-google-genai wraps `ClientError` in `ChatGoogleGenerativeAIError` subclasses;
    the original is re-raised so callers can read its `code` and quota `details`.

    Args:
        messages: System, history and new user messages.

    Returns:
        The parsed reply.
    """
    try:
        result = _build_llm().invoke(messages)
    except ChatGoogleGenerativeAIError as exc:
        if isinstance(exc.__cause__, ClientError):
            raise exc.__cause__ from None
        raise
    if not isinstance(result, AssistantTurn):
        raise OutputParserException(f"Expected AssistantTurn, got {type(result).__name__}")
    return result
