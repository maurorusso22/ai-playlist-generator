"""Unit tests for the Client Credentials token in src/spotify/app_token.py (respx, offline)."""

import base64
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import pytest
import respx
from pytest_mock import MockerFixture

from src.spotify import app_token, auth
from src.spotify.app_token import TOKEN_URL
from src.spotify.client import SpotifyAuthError

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)  # Frozen start time for expiry checks
TOKEN_BODY = {"access_token": "app-access", "token_type": "Bearer", "expires_in": 3600}


@pytest.fixture
def clock(mocker: MockerFixture) -> list[datetime]:
    """Freeze the module clock and drop any cached token; tests move time via clock[0].

    Args:
        mocker: pytest-mock fixture.

    Returns:
        A one-item list holding the current fake time.
    """
    current = [NOW]
    mocker.patch.object(app_token, "_now", side_effect=lambda: current[0])
    mocker.patch.object(app_token, "_app_token", None)
    return current


@pytest.fixture
def accounts(clock: list[datetime]) -> Iterator[respx.MockRouter]:
    """Mock the accounts service on a frozen clock; unmocked requests fail.

    Args:
        clock: Frozen clock fixture.

    Returns:
        The respx router, yielded for route setup.
    """
    with respx.mock(assert_all_called=False) as router:
        yield router


def test_app_token_uses_basic_auth_and_is_reused_until_expiry(
    accounts: respx.MockRouter, clock: list[datetime]
) -> None:
    """Client Credentials with Basic auth; reused until expiry, fetched again after it."""
    route = accounts.post(TOKEN_URL).respond(200, json=TOKEN_BODY)
    assert auth.get_app_token() == "app-access"
    expected = base64.b64encode(b"test-client-id:test-client-secret").decode()
    assert route.calls.last.request.headers["Authorization"] == f"Basic {expected}"
    assert parse_qs(route.calls.last.request.content.decode()) == {
        "grant_type": ["client_credentials"]
    }
    clock[0] = NOW + timedelta(seconds=3000)
    auth.get_app_token()
    assert route.call_count == 1
    clock[0] = NOW + timedelta(seconds=3600)
    auth.get_app_token()
    assert route.call_count == 2


def test_parallel_callers_fetch_the_token_once(accounts: respx.MockRouter) -> None:
    """The lock lets only one of many concurrent callers hit the token endpoint."""
    route = accounts.post(TOKEN_URL).respond(200, json=TOKEN_BODY)
    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(lambda _: auth.get_app_token(), range(16)))
    assert set(tokens) == {"app-access"}
    assert route.call_count == 1


def test_bad_client_credentials_raise_auth_error(accounts: respx.MockRouter) -> None:
    """A 401 from the token endpoint carries the OAuth error description."""
    body = {"error": "invalid_client", "error_description": "Invalid client secret"}
    accounts.post(TOKEN_URL).respond(401, json=body)
    with pytest.raises(SpotifyAuthError) as exc_info:
        auth.get_app_token()
    assert exc_info.value.message == "Invalid client secret"
    assert exc_info.value.reason == "invalid_client"
