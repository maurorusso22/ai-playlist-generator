"""One structured Gemini call per user turn, followed by the deterministic guard.

The prompt holds only the system rules, the LLM's own previous draft and the user/assistant
text messages: `notice` messages and Spotify-resolved data never reach the LLM.
"""

import logging
import time
from collections.abc import Sequence
from functools import lru_cache

from google.genai.errors import ClientError
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError

from src.config import OVERGENERATION_RATIO, PLAYLIST_HARD_MAX_SIZE, PLAYLIST_MIN_SIZE, get_settings
from src.criteria import apply_guard, candidate_count, clamp_size
from src.prompt import SYSTEM_PROMPT, format_draft_context
from src.schema import AssistantTurn, ChatMessage, PlaylistDraft

HISTORY_MAX_MESSAGES = 20  # Last user/assistant messages sent to the LLM (10 exchanges)
PARSE_ATTEMPTS = 2  # A structured-output parsing failure is retried once
LLM_MAX_RETRIES = 2  # Total SDK attempts (1 retry): the default 6 delays 429 feedback by ~30 s
LLM_ROLES = ("user", "assistant")  # Roles sent to the LLM; `notice` may carry Spotify data

_logger = logging.getLogger(__name__)


class AssistantUnavailableError(RuntimeError):
    """Raised when the LLM reply cannot be parsed, even after one retry."""


@lru_cache(maxsize=1)
def _build_llm() -> Runnable[list[BaseMessage], object]:
    """Build the Gemini model bound to the `AssistantTurn` schema, once and lazily.

    Returns:
        A runnable whose `invoke` returns a parsed `AssistantTurn`.
    """
    settings = get_settings()
    llm = ChatGoogleGenerativeAI(
        model=settings.llm_model,
        google_api_key=settings.google_api_key,
        max_retries=LLM_MAX_RETRIES,
    )
    structured: Runnable[list[BaseMessage], object] = llm.with_structured_output(AssistantTurn)
    return structured


def _system_prompt(draft: PlaylistDraft | None) -> str:
    """Fill the system prompt with the size settings and append the current draft.

    Args:
        draft: The LLM's own current draft, or None.

    Returns:
        The full system message text.
    """
    default_size = clamp_size(None)
    max_size = clamp_size(PLAYLIST_HARD_MAX_SIZE)  # PLAYLIST_MAX_SIZE may lower the cap
    rules = SYSTEM_PROMPT.format(
        min_size=PLAYLIST_MIN_SIZE,
        default_size=default_size,
        max_size=max_size,
        extra_percent=round(OVERGENERATION_RATIO * 100),
        default_candidates=candidate_count(default_size),
        max_candidates=candidate_count(max_size),
    )
    return rules + format_draft_context(draft)


def _history_messages(history: Sequence[ChatMessage], user_text: str) -> list[BaseMessage]:
    """Convert the last user/assistant messages to LangChain messages, dropping notices.

    Args:
        history: Stored chat messages, oldest first.
        user_text: The new user message, sent separately after the history.

    Returns:
        At most HISTORY_MAX_MESSAGES Human/AI messages, oldest first.
    """
    texts = [m for m in history if m.role in LLM_ROLES]
    if texts and texts[-1].role == "user" and texts[-1].content == user_text:
        texts = texts[:-1]  # The caller already appended the new message: avoid sending it twice
    return [
        HumanMessage(m.content) if m.role == "user" else AIMessage(m.content)
        for m in texts[-HISTORY_MAX_MESSAGES:]
    ]


def _invoke(messages: list[BaseMessage]) -> AssistantTurn:
    """Call the LLM once, surfacing Gemini client errors as `google.genai.errors.ClientError`.

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


def run_turn(
    user_text: str, history: Sequence[ChatMessage], draft: PlaylistDraft | None
) -> AssistantTurn:
    """Run one conversation turn: a structured LLM call, then the minimum-criteria guard.

    Gemini `ClientError`/`ServerError` propagate unchanged for the UI to map.

    Args:
        user_text: The new user message.
        history: Previous chat messages, without the new one; notices are filtered out.
        draft: The LLM's own current draft (never resolved Spotify tracks), or None.

    Returns:
        The guarded assistant turn.
    """
    messages = [
        SystemMessage(_system_prompt(draft)),
        *_history_messages(history, user_text),
        HumanMessage(user_text),
    ]
    for attempt in range(1, PARSE_ATTEMPTS + 1):
        started = time.perf_counter()
        try:
            turn = _invoke(messages)
        except OutputParserException:
            _logger.warning("Unparsable LLM reply (attempt %d of %d)", attempt, PARSE_ATTEMPTS)
            continue
        _logger.info("LLM turn took %.2fs", time.perf_counter() - started)
        return apply_guard(turn, has_draft=draft is not None)
    raise AssistantUnavailableError("The assistant is temporarily unavailable.")
