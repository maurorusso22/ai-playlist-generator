"""Spotify token endpoint access and the cached Client Credentials (app) token.

Every token request is made from the backend with HTTP Basic auth, so the Client Secret never
leaves the server. The app token is a credential (not Spotify content) reused until shortly
before it expires; it is only used for public catalog data.
"""

import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from src.config.secrets import get_secrets
from src.config.settings import get_settings
from src.spotify.errors import INVALID_GRANT, SpotifyError, SpotifyReauthRequired
from src.spotify.retry import REQUEST_TIMEOUT_S, send_with_retries

TOKEN_URL = "https://accounts.spotify.com/api/token"  # noqa: S105 - OAuth token endpoint URL
APP_TOKEN_MARGIN_S = 60  # Fetch a new app token this many seconds before it expires

_app_token: str | None = None  # Cached Client Credentials token, shared by all sessions
_app_token_expires_at = datetime.min.replace(tzinfo=UTC)  # When to fetch a new app token
_app_token_lock = threading.Lock()  # Parallel searches and sessions must not fetch it twice


def _now() -> datetime:
    """Current time; patched in tests to simulate expiry.

    Returns:
        The current timezone-aware UTC datetime.
    """
    return datetime.now(UTC)


def post_token(data: dict[str, str]) -> dict[str, Any]:
    """Call the token endpoint with the app's Basic credentials and the retry policy.

    Args:
        data: Form fields, including `grant_type`.

    Returns:
        The JSON token response; a rejected grant raises SpotifyReauthRequired.
    """
    credentials = (get_settings().spotify.client_id, get_secrets().spotify_client_secret)
    with httpx.Client(timeout=REQUEST_TIMEOUT_S) as http:
        try:
            response = send_with_retries(http, "POST", TOKEN_URL, data=data, auth=credentials)
        except SpotifyError as exc:
            if exc.reason == INVALID_GRANT:
                raise SpotifyReauthRequired(exc.status, exc.message, exc.reason) from exc
            raise
    payload: dict[str, Any] = response.json()
    return payload


def get_app_token() -> str:
    """Return the Client Credentials token, fetching a new one when missing or about to expire.

    Returns:
        A valid app access token.
    """
    global _app_token, _app_token_expires_at
    with _app_token_lock:
        if _app_token is None or _now() >= _app_token_expires_at:
            payload = post_token({"grant_type": "client_credentials"})
            lifetime = max(int(payload["expires_in"]) - APP_TOKEN_MARGIN_S, 0)
            _app_token = str(payload["access_token"])
            _app_token_expires_at = _now() + timedelta(seconds=lifetime)
        return _app_token
