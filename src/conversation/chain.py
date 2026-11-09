"""One structured LLM call per user turn, followed by the deterministic guard.

The engine is chosen by `llm.provider` (Gemini or Claude). The prompt holds only the system
rules, the LLM's own previous draft and the user/assistant text messages: `notice` messages
and Spotify-resolved data never reach the LLM.
"""

import logging
import time
from collections.abc import Sequence

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from src.config.constants import OVERGENERATION_RATIO, PLAYLIST_HARD_MAX_SIZE, PLAYLIST_MIN_SIZE
from src.config.settings import get_settings
from src.conversation.criteria import apply_guard, candidate_count, clamp_size
from src.conversation.prompt import SYSTEM_PROMPT, format_draft_context
from src.conversation.title import MAX_TITLE_LENGTH
from src.llm import claude, gemini
from src.models.conversation.assistant_turn import AssistantTurn
from src.models.conversation.playlist_draft import PlaylistDraft
from src.models.session.chat_message import ChatMessage

HISTORY_MAX_MESSAGES = 20  # Last user/assistant messages sent to the LLM (10 exchanges)
PARSE_ATTEMPTS = 2  # A structured-output parsing failure is retried once
LLM_ROLES = ("user", "assistant")  # Roles sent to the LLM; `notice` may carry Spotify data

_logger = logging.getLogger(__name__)


class AssistantUnavailableError(RuntimeError):
    """Raised when the LLM reply cannot be parsed, even after one retry."""


def _system_prompt(draft: PlaylistDraft | None) -> str:
    """Fill the system prompt with the size settings and append the current draft.

    Args:
        draft: The LLM's own current draft, or None.

    Returns:
        The full system message text.
    """
    default_size = clamp_size(None)
    max_size = clamp_size(PLAYLIST_HARD_MAX_SIZE)  # playlist.max_size may lower the cap
    rules = SYSTEM_PROMPT.format(
        min_size=PLAYLIST_MIN_SIZE,
        default_size=default_size,
        max_size=max_size,
        extra_percent=round(OVERGENERATION_RATIO * 100),
        default_candidates=candidate_count(default_size),
        max_candidates=candidate_count(max_size),
        max_title_length=MAX_TITLE_LENGTH,
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
    """Call the engine selected by `llm.provider` once.

    Args:
        messages: System, history and new user messages.

    Returns:
        The parsed reply.
    """
    if get_settings().llm.provider == "claude":
        return claude.invoke(messages)
    return gemini.invoke(messages)


def run_turn(
    user_text: str, history: Sequence[ChatMessage], draft: PlaylistDraft | None
) -> AssistantTurn:
    """Run one conversation turn: a structured LLM call, then the minimum-criteria guard.

    Provider errors (Gemini `ClientError`/`ServerError`, Anthropic `APIError`) propagate
    unchanged for the UI to map.

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
