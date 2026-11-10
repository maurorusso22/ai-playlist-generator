"""Unit tests for the LLM (Gemini, Claude) and Spotify error-to-message mapping."""

import anthropic
import httpx2
import pytest
from google.genai.errors import ClientError, ServerError

from src.config.errors import ConfigError
from src.conversation.chain import AssistantUnavailableError
from src.spotify.errors import (
    SpotifyAuthError,
    SpotifyBadRequestError,
    SpotifyError,
    SpotifyForbiddenError,
    SpotifyNotFoundError,
    SpotifyQuotaError,
    SpotifyRateLimitError,
    SpotifyReauthRequired,
    SpotifyServerError,
)
from src.ui import errors


def _gemini(code: int, quota_id: str | None = None) -> ClientError:
    """Build a Gemini ClientError as the google-genai SDK raises it.

    Args:
        code: HTTP status.
        quota_id: QuotaFailure violation id, if any.

    Returns:
        The error.
    """
    details = [{"violations": [{"quotaId": quota_id}]}] if quota_id else []
    body = {"error": {"code": code, "message": "m", "status": "S", "details": details}}
    return ClientError(code, body)


def _claude(error: type[anthropic.APIStatusError], code: int) -> anthropic.APIStatusError:
    """Build an Anthropic API error as the SDK raises it.

    Args:
        error: The SDK error class.
        code: HTTP status.

    Returns:
        The error.
    """
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return error("m", response=httpx2.Response(code, request=request), body=None)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_claude(anthropic.EnforcedSpendLimitReachedError, 429), errors.BUDGET_EXHAUSTED),
        (_claude(anthropic.RateLimitError, 429), errors.AI_BUSY),
        (_claude(anthropic.OverloadedError, 529), errors.UNAVAILABLE),
        (_claude(anthropic.InternalServerError, 500), errors.UNAVAILABLE),
        (anthropic.APITimeoutError(httpx2.Request("POST", "https://x.test")), errors.UNAVAILABLE),
        (_claude(anthropic.NotFoundError, 404), errors.MISCONFIGURED),
        (_claude(anthropic.AuthenticationError, 401), errors.MISCONFIGURED),
        (ConfigError("Missing ANTHROPIC_API_KEY"), errors.MISCONFIGURED),
        (_claude(anthropic.BadRequestError, 400), errors.GENERIC),
    ],
)
def test_claude_errors_are_mapped(exc: Exception, expected: str) -> None:
    """Spend cap, rate limit, outages and misconfiguration each get their own message."""
    assert errors.assistant_error_message(exc) == expected


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (_gemini(429, "GenerateRequestsPerDayPerProjectPerModel-FreeTier"), errors.DAILY_QUOTA),
        (_gemini(429, "GenerateRequestsPerMinutePerProjectPerModel"), errors.DAILY_QUOTA),
        (_gemini(429), errors.DAILY_QUOTA),
        (_gemini(404), errors.MISCONFIGURED),
        (_gemini(400), errors.GENERIC),
        (ServerError(503, {"error": {"code": 503, "message": "overloaded"}}), errors.UNAVAILABLE),
        (AssistantUnavailableError("unparsable"), errors.UNAVAILABLE),
        (RuntimeError("boom"), errors.GENERIC),
    ],
)
def test_assistant_errors_are_mapped(exc: Exception, expected: str) -> None:
    """Every LLM failure maps to its user message."""
    assert errors.assistant_error_message(exc) == expected


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (SpotifyQuotaError(429, "q", "QUOTA_EXCEEDED"), errors.SPOTIFY_BUSY),
        (SpotifyRateLimitError(429, "slow"), errors.SPOTIFY_BUSY),
        (SpotifyServerError(502, "bad gateway"), errors.SPOTIFY_BUSY),
        (SpotifyAuthError(401, "expired"), errors.LOGIN_EXPIRED),
        (SpotifyReauthRequired(400, "revoked", "invalid_grant"), errors.LOGIN_EXPIRED),
        (SpotifyForbiddenError(403, "not allowlisted"), errors.INVITE_ONLY),
    ],
)
def test_spotify_errors_are_mapped(exc: SpotifyError, expected: str) -> None:
    """Spotify quota, rate-limit, 5xx, auth and 403 errors map to their messages."""
    assert errors.spotify_error_message(exc) == expected


@pytest.mark.parametrize("cls", [SpotifyBadRequestError, SpotifyNotFoundError, SpotifyError])
def test_spotify_message_is_shown_escaped(cls: type[SpotifyError]) -> None:
    """Spotify's own message is shown escaped for 400, 404 and other errors."""
    message = errors.spotify_error_message(cls(400, "Bad <b>id</b> _x_"))
    assert message == r"Spotify couldn't complete the request: Bad \<b\>id\</b\> \_x\_"


def test_escape_markdown_flattens_and_truncates() -> None:
    """Markdown, LaTeX and directive syntax is escaped, flattened and truncated."""
    escaped = errors.escape_markdown("# Title\n\n![img](https://x) $x$ :red[y]" + "a" * 500)
    assert "\n" not in escaped and escaped.startswith(r"\# Title \!\[img\]")
    assert r"\$x\$" in escaped and r"\:red\[y\]" in escaped
    assert escaped.count("a") <= errors.MAX_PROVIDER_TEXT
