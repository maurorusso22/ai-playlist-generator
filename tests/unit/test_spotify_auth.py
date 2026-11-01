"""Unit tests for the Authorization Code flow in src/spotify/auth.py (respx, offline)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from pydantic import SecretStr
from pytest_mock import MockerFixture

from src.schema import SpotifyTokens
from src.spotify import auth
from src.spotify.app_token import TOKEN_URL
from src.spotify.client import API_BASE_URL, SpotifyClient, SpotifyForbiddenError

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)  # Frozen clock for expiry checks
TOKEN_BODY = {"access_token": "new-access", "token_type": "Bearer", "expires_in": 3600}


@pytest.fixture
def accounts(mocker: MockerFixture) -> Iterator[respx.MockRouter]:
    """Freeze the clock at NOW and mock Spotify's hosts; unmocked requests fail.

    Args:
        mocker: pytest-mock fixture.

    Returns:
        The respx router, yielded for route setup.
    """
    mocker.patch.object(auth, "_now", return_value=NOW)
    with respx.mock(assert_all_called=False) as router:
        yield router


def _form(route: respx.Route) -> dict[str, str]:
    """Decode the form body of the route's last request.

    Args:
        route: A called respx route.

    Returns:
        The form fields as a flat dict.
    """
    fields = parse_qs(route.calls.last.request.content.decode())
    return {name: values[0] for name, values in fields.items()}


def _tokens(expires_in_s: int) -> SpotifyTokens:
    """Build user tokens expiring relative to NOW.

    Args:
        expires_in_s: Seconds until the access token expires.

    Returns:
        Tokens with a known refresh token.
    """
    expires_at = NOW + timedelta(seconds=expires_in_s)
    return SpotifyTokens(
        access_token=SecretStr("old-access"), refresh_token=SecretStr("old-refresh"),
        expires_at=expires_at, user_id="u1", display_name="Mauro",
    )  # fmt: skip


def test_build_authorize_url() -> None:
    """The consent URL carries code flow, the only scope, the exact redirect URI and state."""
    url = urlparse(auth.build_authorize_url("state-123"))
    params = {name: values[0] for name, values in parse_qs(url.query).items()}
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://accounts.spotify.com/authorize"
    assert params == {
        "client_id": "test-client-id",
        "response_type": "code",
        "redirect_uri": "http://127.0.0.1:8501/",
        "scope": "playlist-modify-private",
        "state": "state-123",
    }


def test_exchange_code(accounts: respx.MockRouter) -> None:
    """The code exchange posts the documented fields and computes the expiry."""
    body = TOKEN_BODY | {"refresh_token": "new-refresh"}
    route = accounts.post(TOKEN_URL).respond(200, json=body)
    tokens = auth.exchange_code("abc")
    assert _form(route) == {
        "grant_type": "authorization_code",
        "code": "abc",
        "redirect_uri": "http://127.0.0.1:8501/",
    }
    assert tokens.access_token.get_secret_value() == "new-access"
    assert tokens.refresh_token.get_secret_value() == "new-refresh"
    assert tokens.expires_at == NOW + timedelta(seconds=3600)


def test_refresh_keeps_old_refresh_token(accounts: respx.MockRouter) -> None:
    """A refresh response without refresh_token keeps the old one and the user fields."""
    route = accounts.post(TOKEN_URL).respond(200, json=TOKEN_BODY)
    tokens = auth.refresh_tokens(_tokens(30))
    assert _form(route) == {"grant_type": "refresh_token", "refresh_token": "old-refresh"}
    assert tokens.refresh_token.get_secret_value() == "old-refresh"
    assert tokens.access_token.get_secret_value() == "new-access"
    assert (tokens.user_id, tokens.display_name) == ("u1", "Mauro")


def test_ensure_fresh_refreshes_only_inside_window(accounts: respx.MockRouter) -> None:
    """Tokens valid for more than 60 s are returned as is; closer to expiry they refresh."""
    route = accounts.post(TOKEN_URL).respond(200, json=TOKEN_BODY)
    fresh = _tokens(120)
    assert auth.ensure_fresh(fresh) is fresh
    assert route.call_count == 0
    assert auth.ensure_fresh(_tokens(30)).access_token.get_secret_value() == "new-access"
    assert route.call_count == 1


def test_invalid_grant_requires_reauthorization(accounts: respx.MockRouter) -> None:
    """A rejected refresh token raises SpotifyReauthRequired."""
    body = {"error": "invalid_grant", "error_description": "Refresh token revoked"}
    accounts.post(TOKEN_URL).respond(400, json=body)
    with pytest.raises(auth.SpotifyReauthRequired) as exc_info:
        auth.refresh_tokens(_tokens(30))
    assert exc_info.value.message == "Refresh token revoked"


def test_verify_state() -> None:
    """Only a non-empty exact match passes."""
    state = auth.new_oauth_state()
    assert auth.verify_state(state, state)
    assert not auth.verify_state(state, auth.new_oauth_state())
    assert not auth.verify_state(state, "")
    assert not auth.verify_state(None, state)


def test_tokens_repr_masks_secrets() -> None:
    """repr() never shows the access or refresh token."""
    text = repr(_tokens(60))
    assert "old-access" not in text
    assert "old-refresh" not in text


def test_get_me_403_is_forbidden(accounts: respx.MockRouter) -> None:
    """A non-allowlisted user surfaces as SpotifyForbiddenError."""
    body = {"error": {"status": 403, "message": "User not registered in the Developer Dashboard"}}
    accounts.get(f"{API_BASE_URL}/me").mock(return_value=httpx.Response(403, json=body))
    with pytest.raises(SpotifyForbiddenError):
        SpotifyClient().get_me("user-token")
