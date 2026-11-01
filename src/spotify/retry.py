"""HTTP sending with Spotify's rate-limit policy: bounded retries, never immediate.

A `429` waits `Retry-After` seconds when the header is present, otherwise (and for `5xx`) an
exponential backoff with jitter. Waits longer than `MAX_RETRY_AFTER_S` are not attempted, to
keep the UI responsive. Request headers and bodies are never logged (they carry tokens).
"""

import logging
import random
import time
from typing import Any

import httpx

from src.spotify.errors import (
    SpotifyError,
    SpotifyRateLimitError,
    SpotifyServerError,
    error_from_response,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 10.0  # Per-request timeout for every Spotify call, in seconds
MAX_RETRIES = 3  # Retries after the first attempt on 429, 5xx or a failed GET connection
BACKOFF_BASE_S = 1.0  # First backoff delay in seconds, doubled on every retry
MAX_RETRY_AFTER_S = 10.0  # Longest single wait accepted, in seconds; longer waits fail fast
UNREACHABLE_STATUS = 503  # Status reported when Spotify sent no response at all


def _jitter() -> float:
    """Random extra delay that spreads retries from parallel workers apart.

    Returns:
        Seconds to add to the backoff delay, between 0 and BACKOFF_BASE_S.
    """
    return random.uniform(0, BACKOFF_BASE_S)  # noqa: S311 - timing jitter, not cryptography


def _backoff(attempt: int) -> float:
    """Exponential backoff delay with jitter, capped at MAX_RETRY_AFTER_S.

    Args:
        attempt: Zero-based index of the attempt that just failed.

    Returns:
        Seconds to wait, always at least BACKOFF_BASE_S.
    """
    return min(BACKOFF_BASE_S * 2.0**attempt + _jitter(), MAX_RETRY_AFTER_S)


def _retry_delay(response: httpx.Response, attempt: int) -> float | None:
    """Seconds to wait before retrying a 429/5xx response.

    Args:
        response: The retryable error response.
        attempt: Zero-based index of the attempt that just failed.

    Returns:
        The `Retry-After` value if present and positive, else the backoff; None when too long.
    """
    try:
        retry_after = float(response.headers.get("Retry-After", 0))
    except ValueError:
        retry_after = 0.0
    if retry_after > MAX_RETRY_AFTER_S:
        return None
    return retry_after if retry_after > 0 else _backoff(attempt)


def send_with_retries(http: httpx.Client, method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Send a request, retrying rate limits and server errors with bounded waits.

    Connection failures are retried only for GET: a POST may have reached Spotify, and
    repeating it could create a second playlist.

    Args:
        http: The httpx client used to send the request.
        method: HTTP method, e.g. "GET".
        url: Absolute URL of the endpoint.
        **kwargs: Extra arguments for `httpx.Client.request` (params, json, data, headers, auth).

    Returns:
        The successful (2xx) response.
    """
    attempt = 0
    while True:
        try:
            response = http.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            logger.warning("Spotify %s %s failed: %s", method, url, type(exc).__name__)
            if method != "GET" or attempt == MAX_RETRIES:
                message = f"Spotify could not be reached ({type(exc).__name__})"
                raise SpotifyServerError(UNREACHABLE_STATUS, message) from exc
            time.sleep(_backoff(attempt))
            attempt += 1
            continue
        if response.is_success:
            return response
        error = error_from_response(response)
        _log_error(method, response, error)
        retryable = isinstance(error, SpotifyRateLimitError | SpotifyServerError)
        delay = _retry_delay(response, attempt) if retryable else None
        if delay is None or attempt == MAX_RETRIES:
            raise error
        time.sleep(delay)
        attempt += 1


def _log_error(method: str, response: httpx.Response, error: SpotifyError) -> None:
    """Log an error response with Spotify's message; the query string and headers are omitted.

    Args:
        method: HTTP method of the request.
        response: The error response.
        error: The exception built from the response.
    """
    logger.warning(
        "Spotify %s %s returned %s: %s",
        method,
        response.request.url.path,
        error.status,
        error.message,
    )
