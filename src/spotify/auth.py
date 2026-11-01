"""Spotify OAuth: app token access plus the backend Authorization Code flow.

Only the `playlist-modify-private` scope is requested. The Client Credentials token lives in
`src/spotify/app_token.py` and is re-exported here, so callers use a single auth module.
"""

import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from pydantic import SecretStr

from src.config.constants import SPOTIFY_SCOPE
from src.config.settings import get_settings
from src.schema import SpotifyTokens
from src.spotify.app_token import get_app_token, post_token
from src.spotify.errors import SpotifyReauthRequired

__all__ = [
    "SpotifyReauthRequired",
    "build_authorize_url",
    "ensure_fresh",
    "exchange_code",
    "get_app_token",
    "new_oauth_state",
    "refresh_tokens",
    "verify_state",
]

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"  # OAuth consent page
REFRESH_MARGIN_S = 60  # Refresh a user token expiring within this many seconds
STATE_BYTES = 32  # Random bytes in the OAuth `state` (CSRF protection)


def _now() -> datetime:
    """Current time; patched in tests to simulate expiry.

    Returns:
        The current timezone-aware UTC datetime.
    """
    return datetime.now(UTC)


def new_oauth_state() -> str:
    """Generate a random OAuth `state` to store in the session before the redirect.

    Returns:
        A URL-safe random string.
    """
    return secrets.token_urlsafe(STATE_BYTES)


def verify_state(expected: str | None, received: str | None) -> bool:
    """Compare the stored and returned `state` in constant time.

    Args:
        expected: State stored in the session.
        received: State from the callback's query string.

    Returns:
        True only when both are non-empty and equal.
    """
    if not expected or not received:
        return False
    return secrets.compare_digest(expected.encode(), received.encode())


def build_authorize_url(state: str) -> str:
    """Build the Spotify consent URL for the Authorization Code flow.

    Args:
        state: The OAuth state stored in the session.

    Returns:
        The full https://accounts.spotify.com/authorize URL.
    """
    spotify = get_settings().spotify
    params = {
        "client_id": spotify.client_id,
        "response_type": "code",
        "redirect_uri": spotify.redirect_uri,
        "scope": SPOTIFY_SCOPE,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code(code: str) -> SpotifyTokens:
    """Exchange an authorization code for tokens; the caller fills user_id/display_name.

    Args:
        code: The `code` query parameter of the callback.

    Returns:
        The user's tokens with their expiry.
    """
    redirect_uri = get_settings().spotify.redirect_uri
    payload = post_token(
        {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
    )
    return SpotifyTokens(
        access_token=SecretStr(payload["access_token"]),
        refresh_token=SecretStr(payload["refresh_token"]),
        expires_at=_now() + timedelta(seconds=int(payload["expires_in"])),
    )


def refresh_tokens(tokens: SpotifyTokens) -> SpotifyTokens:
    """Get a new access token; a rejected refresh token raises SpotifyReauthRequired.

    Args:
        tokens: The user's current tokens.

    Returns:
        Updated tokens, keeping the old refresh token when Spotify returns none.
    """
    refresh = tokens.refresh_token.get_secret_value()
    payload = post_token({"grant_type": "refresh_token", "refresh_token": refresh})
    new_refresh = payload.get("refresh_token")
    refreshed: SpotifyTokens = tokens.model_copy(
        update={
            "access_token": SecretStr(payload["access_token"]),
            "refresh_token": SecretStr(new_refresh) if new_refresh else tokens.refresh_token,
            "expires_at": _now() + timedelta(seconds=int(payload["expires_in"])),
        }
    )
    return refreshed


def ensure_fresh(tokens: SpotifyTokens) -> SpotifyTokens:
    """Refresh the access token (valid 1 h) when it expires within REFRESH_MARGIN_S.

    Args:
        tokens: The user's current tokens.

    Returns:
        The same object when still fresh (callers persist only a new object), else new tokens.
    """
    if tokens.expires_at - _now() > timedelta(seconds=REFRESH_MARGIN_S):
        return tokens
    return refresh_tokens(tokens)
