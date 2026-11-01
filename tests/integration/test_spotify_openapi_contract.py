"""Contract test: the Spotify client only uses documented, non-deprecated Web API endpoints.

Downloads Spotify's official OpenAPI schema (network only, no credentials; skipped offline),
records every request the client makes under respx, and checks each method, path, query
parameter and JSON field against the schema. Run with:

    pytest tests/integration/test_spotify_openapi_contract.py
"""

import inspect
import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import yaml

from src.spotify.client import API_BASE_URL, SEARCH_LIMIT_MAX, SpotifyClient

SCHEMA_URL = (
    "https://developer.spotify.com/reference/web-api/open-api-schema.yaml"  # Source of truth
)
SPOTIFY_SRC = Path(__file__).resolve().parents[2] / "src" / "spotify"  # Package scanned below
EXPECTED_ENDPOINTS = {  # Every (method, path template) the client is meant to call
    ("get", "/search"),
    ("get", "/me"),
    ("post", "/me/playlists"),
    ("post", "/playlists/{playlist_id}/items"),
}
DEPRECATED_PATTERNS = (  # Deprecated paths as they would appear in source code
    r"/playlists/\{[^}]*\}/tracks",
    r"/users/",
    r"[\"']/tracks\b",
)


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    """Download and parse the official OpenAPI schema, skipping when offline.

    Returns:
        The parsed schema.
    """
    try:
        response = httpx.get(SCHEMA_URL, timeout=30, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"OpenAPI schema unavailable: {exc}")
    parsed: dict[str, Any] = yaml.safe_load(response.text)
    return parsed


def _recorded_requests() -> list[httpx.Request]:
    """Exercise every client method under respx and record the requests.

    Returns:
        The requests the client sent, in call order.
    """
    body = {"tracks": {"items": []}, "id": "p1", "snapshot_id": "s1"}
    with respx.mock(base_url=API_BASE_URL) as router:
        router.route().respond(200, json=body)
        client = SpotifyClient()
        client.search_tracks("token", "Animals", "Martin Garrix", "IT")
        client.get_me("token")
        client.create_playlist("token", "Mix", "Desc")
        client.add_items("token", "p1", ["spotify:track:t1"])
        client.close()
        return [call.request for call in router.calls]


def _operation(schema: dict[str, Any], request: httpx.Request) -> tuple[str, dict[str, Any]]:
    """Find the schema operation matching a recorded request.

    Args:
        schema: Parsed OpenAPI schema.
        request: A request sent by the client.

    Returns:
        The path template and its operation object.
    """
    path, method = request.url.path.removeprefix("/v1"), request.method.lower()
    for template, item in schema["paths"].items():
        pattern = "^" + re.sub(r"\{[^}]+\}", "[^/]+", template) + "$"
        if (template == path or re.match(pattern, path)) and method in item:
            return template, item[method]
    raise AssertionError(f"{request.method} {path} is not in the OpenAPI schema")


def _resolve(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """Follow a local `$ref` if present.

    Args:
        schema: Parsed OpenAPI schema.
        node: A schema node that may be a reference.

    Returns:
        The referenced node, or the node itself.
    """
    target = schema if "$ref" in node else node
    for part in node["$ref"].removeprefix("#/").split("/") if "$ref" in node else []:
        target = target[part]
    return target


def test_client_endpoints_exist_and_are_not_deprecated(schema: dict[str, Any]) -> None:
    """Every (method, path) the client calls is documented and not deprecated."""
    seen = set()
    for request in _recorded_requests():
        template, operation = _operation(schema, request)
        assert not operation.get("deprecated"), f"{template} is deprecated"
        seen.add((request.method.lower(), template))
    assert seen == EXPECTED_ENDPOINTS


def test_spike_cleanup_endpoint_is_documented(schema: dict[str, Any]) -> None:
    """DELETE /me/library, used by the spike's cleanup step, exists and is not deprecated."""
    assert not schema["paths"]["/me/library"]["delete"].get("deprecated")


def test_client_parameters_and_body_fields_exist(schema: dict[str, Any]) -> None:
    """Query parameters and JSON body fields sent by the client are all in the schema."""
    for request in _recorded_requests():
        template, operation = _operation(schema, request)
        params = [_resolve(schema, p) for p in operation.get("parameters", [])]
        names = {p["name"] for p in params if p.get("in") == "query"}
        assert set(request.url.params) <= names, f"unknown query parameter for {template}"
        if request.content:
            body_schema = operation["requestBody"]["content"]["application/json"]["schema"]
            assert set(json.loads(request.content)) <= set(body_schema["properties"])


def test_search_limit_within_schema_maximum(schema: dict[str, Any]) -> None:
    """The client's default and maximum search limit respect the schema's `limit` maximum."""
    operation = schema["paths"]["/search"]["get"]
    params = [_resolve(schema, p) for p in operation["parameters"]]
    maximum = next(p["schema"]["maximum"] for p in params if p["name"] == "limit")
    default = inspect.signature(SpotifyClient.search_tracks).parameters["limit"].default
    assert default <= SEARCH_LIMIT_MAX <= maximum


def test_no_deprecated_paths_in_spotify_package() -> None:
    """None of the deprecated paths appears in src/spotify/ (no network needed)."""
    sources = {path.name: path.read_text() for path in SPOTIFY_SRC.glob("*.py")}
    assert "client.py" in sources
    for name, text in sources.items():
        for pattern in DEPRECATED_PATTERNS:
            assert not re.search(pattern, text), f"{name} matches deprecated {pattern}"
