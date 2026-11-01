"""User-facing messages and the mapping from Gemini and Spotify errors to them.

Errors are logged with their status and provider message, never with tokens. Text that comes
from a provider is escaped before it reaches `st.markdown`-based elements.
"""

import logging
import re

from google.genai.errors import ClientError, ServerError

from src.config.settings import get_settings
from src.conversation.chain import AssistantUnavailableError
from src.spotify.errors import (
    SpotifyAuthError,
    SpotifyError,
    SpotifyForbiddenError,
    SpotifyQuotaError,
    SpotifyRateLimitError,
    SpotifyReauthRequired,
    SpotifyServerError,
)

DAILY_QUOTA = "The AI quota is used up for today. Please come back tomorrow."  # Any Gemini 429
MISCONFIGURED = "The assistant is misconfigured. Please try again later."  # Gemini 404
UNAVAILABLE = "Assistant temporarily unavailable. Please try again."  # 5xx or parse failure
GENERIC = "Something went wrong while generating a reply. Please try again."  # Other errors
SPOTIFY_BUSY = "Spotify is busy, try again in a few minutes."  # Spotify 429/quota/5xx
LOGIN_EXPIRED = "Your Spotify login expired, please log in again."  # 401 or invalid_grant
INVITE_ONLY = (  # Spotify 403: the account is not on the Development Mode allowlist
    "Spotify login is invite-only while this app is in development mode (up to 5 users). "
    "You can keep using it as a guest."
)
SPOTIFY_FAILED = "Spotify couldn't complete the request: {message}"  # Spotify 400/404/other
SAVE_FAILED = "Couldn't save the conversation, please retry."  # Any Firestore API error
DELETE_FAILED = "Couldn't delete the conversation, please retry."  # New chat delete failed
LOAD_FAILED = "Couldn't load your conversation, please reload the page."  # Bootstrap read
RATE_LIMITED = "Too many messages. Please wait a minute and try again."  # FR-14
LOGIN_TOO_SLOW = "Your login took too long, please start again."  # Callback without session
LOGIN_CANCELLED = "Spotify login cancelled."  # Callback with ?error=access_denied
LOGIN_CHECK_FAILED = "Spotify login failed a security check, please try again."  # Bad state
STORAGE_BLOCKED = (  # The browser never read back the session id before the redirect
    "Spotify login needs this site's browser storage, which seems blocked. "
    "You can keep using the app as a guest."
)
MARKDOWN_SPECIALS = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:&])")  # Chars escaped for markdown
MAX_PROVIDER_TEXT = 200  # Longest provider message shown to the user

_logger = logging.getLogger(__name__)


def escape_markdown(text: str) -> str:
    """Neutralize markdown, HTML and LaTeX syntax in untrusted text for st.markdown.

    Args:
        text: Untrusted text (an LLM title, a Spotify display name or error message).

    Returns:
        Single-line text with every markdown special character backslash-escaped.
    """
    flat = " ".join(str(text).split())[:MAX_PROVIDER_TEXT]
    return MARKDOWN_SPECIALS.sub(r"\\\1", flat)


def assistant_error_message(exc: Exception) -> str:
    """Map a failure of the LLM call to a user message, logging it with context.

    Args:
        exc: The exception raised by `chain.run_turn`.

    Returns:
        The message to show.
    """
    if isinstance(exc, ClientError) and exc.code == 429:
        # Per-minute and per-day limits get the same answer: the free tier's daily quota is
        # the one users actually hit, and a single message keeps the UX predictable.
        _logger.warning("Gemini quota exhausted: %s (details: %s)", exc.message, exc.details)
        return DAILY_QUOTA
    if isinstance(exc, ClientError) and exc.code == 404:
        _logger.error("Gemini model not found: %s (%s)", get_settings().llm.model, exc.message)
        return MISCONFIGURED
    if isinstance(exc, ServerError | AssistantUnavailableError):
        _logger.error("Assistant unavailable: %s", exc)
        return UNAVAILABLE
    _logger.exception("Unexpected assistant error", exc_info=exc)
    return GENERIC


def spotify_error_message(exc: SpotifyError) -> str:
    """Map a Spotify error to a user message, logging its status and Spotify's message.

    Args:
        exc: Any SpotifyError subclass.

    Returns:
        The message to show, with Spotify's own text escaped.
    """
    _logger.warning("Spotify error %s (%s): %s", exc.status, exc.reason, exc.message)
    if isinstance(exc, SpotifyQuotaError | SpotifyRateLimitError | SpotifyServerError):
        return SPOTIFY_BUSY
    if isinstance(exc, SpotifyAuthError | SpotifyReauthRequired):
        return LOGIN_EXPIRED
    if isinstance(exc, SpotifyForbiddenError):
        return INVITE_ONLY
    return SPOTIFY_FAILED.format(message=escape_markdown(exc.message))
