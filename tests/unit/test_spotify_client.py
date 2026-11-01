"""Unit tests for src/spotify/client.py endpoints and error mapping (respx, offline)."""

import json
from collections.abc import Iterator

import pytest
import respx
from pytest_mock import MockerFixture

from src.spotify.client import (
    API_BASE_URL,
    SpotifyAuthError,
    SpotifyBadRequestError,
    SpotifyClient,
    SpotifyError,
    SpotifyForbiddenError,
    SpotifyNotFoundError,
)

TOKEN = "user-access-token"  # Fake bearer token; must never appear in logs
TRACK = {"id": "t1", "uri": "spotify:track:t1", "name": "Animals", "artists": []}  # Search item


@pytest.fixture
def api(mocker: MockerFixture) -> Iterator[respx.MockRouter]:
    """Mock the Web API (unmocked requests fail) and make any retry wait instant.

    Args:
        mocker: pytest-mock fixture.

    Returns:
        The respx router, yielded for route setup.
    """
    mocker.patch("src.spotify.retry.time.sleep")
    with respx.mock(base_url=API_BASE_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
def client() -> Iterator[SpotifyClient]:
    """A client owning its httpx.Client, closed after the test.

    Returns:
        The SpotifyClient under test.
    """
    spotify = SpotifyClient()
    yield spotify
    spotify.close()


def test_search_tracks_sends_documented_query(api: respx.MockRouter, client: SpotifyClient) -> None:
    """GET /search carries type, limit, market, the field-filtered q and a Bearer token."""
    route = api.get("/search").respond(200, json={"tracks": {"items": [TRACK, None]}})
    assert client.search_tracks(TOKEN, "Animals", "Martin Garrix", "IT") == [TRACK]
    request = route.calls.last.request
    assert dict(request.url.params) == {
        "q": 'track:"Animals" artist:"Martin Garrix"',
        "type": "track",
        "limit": "5",
        "market": "IT",
    }
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"


def test_search_tracks_strips_double_quotes(api: respx.MockRouter, client: SpotifyClient) -> None:
    """Double quotes in the inputs cannot break the field filter."""
    route = api.get("/search").respond(200, json={"tracks": {"items": []}})
    client.search_tracks(TOKEN, 'The "Real" One', 'DJ "X"', "IT")
    assert route.calls.last.request.url.params["q"] == 'track:"The Real One" artist:"DJ X"'


def test_search_limit_above_schema_maximum_is_rejected(client: SpotifyClient) -> None:
    """The schema caps `limit` at 10."""
    with pytest.raises(ValueError):
        client.search_tracks(TOKEN, "a", "b", "IT", limit=11)


def test_create_playlist_is_private(api: respx.MockRouter, client: SpotifyClient) -> None:
    """POST /me/playlists always sends public=false; no /v1/users/ route is ever called."""
    users = api.route(path__startswith="/v1/users/")
    route = api.post("/me/playlists").respond(201, json={"id": "p1"})
    assert client.create_playlist(TOKEN, "Mix", "Desc") == {"id": "p1"}
    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "Mix", "description": "Desc", "public": False}
    assert not users.called


def test_add_items_single_request(api: respx.MockRouter, client: SpotifyClient) -> None:
    """30 URIs go in exactly one POST /playlists/{id}/items with a JSON body."""
    uris = [f"spotify:track:{i}" for i in range(30)]
    route = api.post("/playlists/p1/items").respond(201, json={"snapshot_id": "s"})
    client.add_items(TOKEN, "p1", uris)
    assert route.call_count == 1
    assert json.loads(route.calls.last.request.content) == {"uris": uris}


def test_add_items_over_limit_or_empty_sends_nothing(
    api: respx.MockRouter, client: SpotifyClient
) -> None:
    """101 URIs raise ValueError and an empty list is a no-op, both without HTTP calls."""
    with pytest.raises(ValueError):
        client.add_items(TOKEN, "p1", [f"spotify:track:{i}" for i in range(101)])
    client.add_items(TOKEN, "p1", [])
    assert api.calls.call_count == 0


def test_get_me_returns_profile(api: respx.MockRouter, client: SpotifyClient) -> None:
    """GET /me returns the profile dict."""
    api.get("/me").respond(200, json={"id": "u1", "display_name": "Mauro"})
    assert client.get_me(TOKEN)["display_name"] == "Mauro"


@pytest.mark.parametrize(
    ("status", "error_class"),
    [
        (400, SpotifyBadRequestError),
        (401, SpotifyAuthError),
        (403, SpotifyForbiddenError),
        (404, SpotifyNotFoundError),
    ],
)
def test_documented_errors_map_to_exceptions(
    api: respx.MockRouter, client: SpotifyClient, status: int, error_class: type[SpotifyError]
) -> None:
    """Each documented status raises its exception with the body's status/message, no retry."""
    body = {"error": {"status": status, "message": f"spotify says {status}"}}
    route = api.get("/me").respond(status, json=body)
    with pytest.raises(error_class) as exc_info:
        client.get_me(TOKEN)
    assert exc_info.value.status == status
    assert exc_info.value.message == f"spotify says {status}"
    assert route.call_count == 1


def test_non_json_error_body_falls_back_to_reason_phrase(
    api: respx.MockRouter, client: SpotifyClient
) -> None:
    """An HTML error page still yields a usable message."""
    api.get("/me").respond(404, text="<html>nope</html>")
    with pytest.raises(SpotifyNotFoundError) as exc_info:
        client.get_me(TOKEN)
    assert exc_info.value.message == "Not Found"
