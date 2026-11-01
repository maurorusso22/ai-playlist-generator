"""Thin httpx client for the four Spotify Web API endpoints the app uses.

Every path, parameter and field comes from Spotify's official OpenAPI schema (checked by
`tests/integration/test_spotify_openapi_contract.py`) and only post-migration endpoints are
used. The access token is passed per call, so one instance serves the app token and all users.
The error hierarchy is re-exported here, so callers import everything Spotify from one module.
"""

from typing import Any
from urllib.parse import quote

import httpx

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
from src.spotify.retry import MAX_RETRIES, REQUEST_TIMEOUT_S, send_with_retries

__all__ = [
    "API_BASE_URL",
    "DEFAULT_SEARCH_LIMIT",
    "ITEMS_MAX_URIS",
    "MAX_RETRIES",
    "SEARCH_LIMIT_MAX",
    "SpotifyAuthError",
    "SpotifyBadRequestError",
    "SpotifyClient",
    "SpotifyError",
    "SpotifyForbiddenError",
    "SpotifyNotFoundError",
    "SpotifyQuotaError",
    "SpotifyRateLimitError",
    "SpotifyReauthRequired",
    "SpotifyServerError",
]

API_BASE_URL = "https://api.spotify.com/v1"  # Web API base URL (the schema's `servers` entry)
DEFAULT_SEARCH_LIMIT = 5  # Search results per suggestion; the schema's default too
SEARCH_LIMIT_MAX = 10  # Schema maximum for `limit` on GET /search
ITEMS_MAX_URIS = 100  # Schema maximum of URIs per POST /playlists/{playlist_id}/items


class SpotifyClient:
    """Web API client: search, profile, playlist creation and item addition."""

    def __init__(self, http: httpx.Client | None = None) -> None:
        """Wrap an httpx client, creating (and owning) one when none is given.

        Args:
            http: Shared httpx client; tests and callers may inject their own.
        """
        self._owns_http = http is None
        self._http = http or httpx.Client(timeout=REQUEST_TIMEOUT_S)

    def close(self) -> None:
        """Close the underlying httpx client if this instance created it."""
        if self._owns_http:
            self._http.close()

    def search_tracks(
        self, token: str, title: str, artist: str, market: str, limit: int = DEFAULT_SEARCH_LIMIT
    ) -> list[dict[str, Any]]:
        """Search the catalog for a track by title and artist (GET /search).

        Args:
            token: Access token (the app's Client Credentials token is enough).
            title: Track title; double quotes are stripped so the field filter stays valid.
            artist: Artist name; double quotes are stripped too.
            market: ISO 3166-1 alpha-2 country code limiting results to playable tracks.
            limit: Number of results, between 1 and SEARCH_LIMIT_MAX.

        Returns:
            The `TrackObject` items of the response, in Spotify's relevance order.
        """
        if not 1 <= limit <= SEARCH_LIMIT_MAX:
            raise ValueError(f"limit must be between 1 and {SEARCH_LIMIT_MAX}, got {limit}")
        title, artist = title.replace('"', ""), artist.replace('"', "")
        query = f'track:"{title}" artist:"{artist}"'
        params = {"q": query, "type": "track", "limit": limit, "market": market}
        body = self._request("GET", "/search", token, params=params).json()
        return [item for item in (body.get("tracks") or {}).get("items") or [] if item]

    def get_me(self, token: str) -> dict[str, Any]:
        """Read the current user's profile (GET /me) without extra scopes.

        Only `id` and `display_name` are used; a 403 means the user is not allowlisted.

        Args:
            token: The user's access token.

        Returns:
            The `PrivateUserObject` as a dict.
        """
        profile: dict[str, Any] = self._request("GET", "/me", token).json()
        return profile

    def create_playlist(self, token: str, name: str, description: str) -> dict[str, Any]:
        """Create a private playlist for the current user (POST /me/playlists).

        `public` is always sent as false, because Spotify defaults it to true.

        Args:
            token: The user's access token (scope playlist-modify-private).
            name: Playlist name.
            description: Playlist description.

        Returns:
            The created `PlaylistObject` (with `id` and `external_urls.spotify`).
        """
        body = {"name": name, "description": description, "public": False}
        playlist: dict[str, Any] = self._request("POST", "/me/playlists", token, json=body).json()
        return playlist

    def add_items(self, token: str, playlist_id: str, uris: list[str]) -> None:
        """Append tracks to a playlist in one request (POST /playlists/{playlist_id}/items).

        Args:
            token: The user's access token (scope playlist-modify-private).
            playlist_id: Spotify id of the playlist.
            uris: Track URIs to add, in order; an empty list is a no-op.
        """
        if len(uris) > ITEMS_MAX_URIS:
            raise ValueError(f"at most {ITEMS_MAX_URIS} URIs per request, got {len(uris)}")
        if uris:
            path = f"/playlists/{quote(playlist_id, safe='')}/items"
            self._request("POST", path, token, json={"uris": list(uris)})

    def _request(self, method: str, path: str, token: str, **kwargs: Any) -> httpx.Response:
        """Call a Web API path with a Bearer token and the retry/error policy.

        Args:
            method: HTTP method.
            path: Path below API_BASE_URL, e.g. "/search".
            token: Access token sent as a Bearer header (never logged).
            **kwargs: Extra arguments for the request (params, json).

        Returns:
            The successful response; failures raise a SpotifyError subclass.
        """
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{API_BASE_URL}{path}"
        return send_with_retries(self._http, method, url, headers=headers, **kwargs)
