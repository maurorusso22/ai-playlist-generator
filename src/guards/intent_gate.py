"""Intent gate: a cheap, fail-open out-of-scope filter in front of Gemini.

Gemini's free tier allows only a few hundred requests a day, so clearly off-topic messages
are stopped by Gemma (a separate, larger quota) before they spend one. The gate is lazy on
purpose: only an unambiguous "OUT" blocks a message, while any other answer, an error, a
quota `429` or a timeout lets it through. A missed off-topic message costs one Gemini call
(and Gemini still declines it); a blocked legitimate one breaks the product.

Gemma sees the new user message and the assistant's last text reply (LLM-generated, never
Spotify data), so short follow-ups such as "yes" or "30" are judged in context.
"""

import logging
import re
import time
from collections.abc import Sequence
from functools import lru_cache

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config.secrets import get_secrets
from src.config.settings import get_settings
from src.guards.gate_prompt import GATE_PROMPT
from src.models.conversation.assistant_turn import AssistantTurn
from src.models.conversation.playlist_criteria import PlaylistCriteria
from src.models.session.chat_message import ChatMessage

GATE_TIMEOUT_S = 3.0  # Client-side HTTP timeout; past it the gate fails open and Gemini answers
GATE_SERVER_DEADLINE_S = 10  # Server deadline header: the API rejects deadlines below 10 s
GATE_MAX_RETRIES = 1  # Single attempt: a retry would cost more latency than the gate saves
GATE_MAX_TOKENS = 8  # The answer is one word (IN or OUT); small headroom, no rambling
MAX_GATED_CHARS = 2000  # Longer messages skip the gate rather than being judged truncated
MAX_CONTEXT_CHARS = 800  # Tail of the assistant reply sent as context (where its question is)
BLOCK_WORD = "OUT"  # The only answer that blocks a message
ALLOW_WORD = "IN"  # The expected answer for in-scope messages
OUT_OF_SCOPE_REPLY = (  # Fixed reply to a blocked message, saved like a normal off-topic turn
    "I can only help with music playlists. Tell me a genre, a mood, a year or era, "
    "an artist, an album or a song, and I'll build one for you."
)

_logger = logging.getLogger(__name__)
_FIRST_WORD = re.compile(r"[A-Za-z]+")  # First word of the answer, ignoring punctuation


@lru_cache(maxsize=1)
def _build_gate() -> ChatGoogleGenerativeAI:
    """Build the Gemma classifier once, lazily (settings are never read at import time).

    google-genai sends the client timeout as the `X-Server-Timeout` deadline unless that
    header is already set, and the API rejects deadlines under 10 s with a 400. Setting the
    header explicitly keeps the short client-side timeout while sending a valid deadline.

    Returns:
        A chat model tuned for a fast, deterministic one-word answer.
    """
    return ChatGoogleGenerativeAI(
        model=get_settings().intent_gate.model,
        google_api_key=get_secrets().google_api_key,
        temperature=0,
        thinking_level="minimal",
        max_tokens=GATE_MAX_TOKENS,
        timeout=GATE_TIMEOUT_S,
        max_retries=GATE_MAX_RETRIES,
        additional_headers={"X-Server-Timeout": str(GATE_SERVER_DEADLINE_S)},
    )


def _framed(text: str, history: Sequence[ChatMessage]) -> str:
    """Wrap the user message and the assistant's last reply in tags for the gate.

    Args:
        text: The new user message.
        history: Stored chat messages before the new one.

    Returns:
        The human message content; notices are skipped because they may hold Spotify data.
    """
    last = next((m.content for m in reversed(history) if m.role == "assistant"), "")
    context = last[-MAX_CONTEXT_CHARS:] or "(none)"
    return (
        f"<assistant_last_message>{context}</assistant_last_message>\n"
        f"<user_message>{text}</user_message>"
    )


def classify(text: str, history: Sequence[ChatMessage]) -> str:
    """Ask Gemma for its verdict on a message, with no fail-open handling.

    Errors propagate, so the AI evals can tell a failed call from a verdict;
    `_is_out_of_scope` is the fail-open wrapper the app uses.

    Args:
        text: The new user message.
        history: Stored chat messages before the new one.

    Returns:
        The answer's first word, uppercased (IN, OUT, another word, or "" when there is none).
    """
    messages = [SystemMessage(GATE_PROMPT), HumanMessage(_framed(text, history))]
    match = _FIRST_WORD.search(_build_gate().invoke(messages).text)
    return match.group().upper() if match else ""


def _is_out_of_scope(text: str, history: Sequence[ChatMessage]) -> bool:
    """Ask Gemma whether the message is clearly off-topic; every doubt or failure says no.

    Args:
        text: The new user message.
        history: Stored chat messages before the new one.

    Returns:
        True only when Gemma's first word is OUT.
    """
    if len(text) > MAX_GATED_CHARS:
        return False
    started = time.perf_counter()
    try:
        word = classify(text, history)
    except Exception as exc:  # Fail open: a gate failure must never block a message
        _logger.warning("Intent gate failed open (%s): %s", type(exc).__name__, exc)
        return False
    if word not in (ALLOW_WORD, BLOCK_WORD):
        _logger.warning("Intent gate failed open on an unexpected answer: %r", word)
    _logger.info("Intent gate: %s in %.2fs", word or "no answer", time.perf_counter() - started)
    return word == BLOCK_WORD


def gate_turn(text: str, history: Sequence[ChatMessage]) -> AssistantTurn | None:
    """Stop a clearly off-topic message before Gemini, with a fixed off-topic turn.

    Never raises: any failure lets the message through to Gemini.

    Args:
        text: The new user message.
        history: Stored chat messages before the new one.

    Returns:
        An `off_topic` turn with OUT_OF_SCOPE_REPLY when Gemma answers OUT, otherwise None.
    """
    if _is_out_of_scope(text, history):
        return AssistantTurn(
            intent="off_topic", criteria=PlaylistCriteria(), message=OUT_OF_SCOPE_REPLY
        )
    return None
