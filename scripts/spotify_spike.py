"""Dev-only Spotify de-risking spike: `python -m scripts.spotify_spike`.

Proves that the real Development Mode app can search the catalog and create a private
playlist for an allowlisted account before any UI is built. Standalone (httpx,
python-dotenv and tomllib only, no `src/` imports) and excluded from the Docker image. Prints one
PASS/FAIL line per step and exits non-zero on the first failure; tokens and the client
secret are never printed.
"""

import os
import secrets
import sys
import tomllib
from pathlib import Path

import httpx
from dotenv import load_dotenv

from scripts.spike_helpers import SpikeError, authorize_user, expect, token

API_URL = "https://api.spotify.com/v1"  # Web API base URL
CONFIG_FILE = Path(__file__).resolve().parents[1] / "config" / "base.toml"  # Non-secret settings
TIMEOUT_S = 15.0  # Per-request timeout in seconds
SEARCH_QUERY = 'track:"Animals" artist:"Martin Garrix"'  # Known mainstream track
FORBIDDEN_CHECKLIST = """Checklist for a 403 on playlist creation:
- the app owner's Spotify Premium subscription is active;
- the logged-in account is in User Management with its exact account email;
- consent was granted for playlist-modify-private (show_dialog=true forces the screen);
- the body uses public: false;
- the endpoint is POST /v1/me/playlists (the per-user playlists endpoint was removed)."""  # Step 5


def search_step(http: httpx.Client, env: dict[str, str]) -> str:
    """Steps 1-2: get the app token and search a known track.

    Args:
        http: HTTP client.
        env: Spotify settings (the secret from `.env`, the rest from config/base.toml).

    Returns:
        URI of the first search result.
    """
    app_token = token(http, env, {"grant_type": "client_credentials"}, "1 client credentials")
    params: dict[str, str | int] = {"q": SEARCH_QUERY, "type": "track", "limit": 5}
    params["market"] = env["SPOTIFY_MARKET"]
    headers = {"Authorization": f"Bearer {app_token}"}
    found = expect(http.get(f"{API_URL}/search", params=params, headers=headers), 200, "2 search")
    items = [item for item in (found.get("tracks") or {}).get("items") or [] if item]
    for item in items:
        artists = ", ".join(artist["name"] for artist in item["artists"])
        print(f"  {item['name']} - {artists} ({item['uri']})")
    if not items:
        raise SpikeError("2 search: no tracks returned")
    return str(items[0]["uri"])


def playlist_steps(http: httpx.Client, headers: dict[str, str], uri: str) -> None:
    """Steps 5-7: create a private playlist, add one track, then try to clean up.

    Args:
        http: HTTP client.
        headers: Authorization header with the user's token.
        uri: Track URI to add.
    """
    body = {"name": f"APG spike {secrets.token_hex(3)}", "public": False}
    body["description"] = "Spotify spike, safe to delete"
    created = http.post(f"{API_URL}/me/playlists", json=body, headers=headers)
    if created.status_code == 403:
        print(FORBIDDEN_CHECKLIST)
    playlist = expect(created, 201, "5 create private playlist")
    playlist_id, url = playlist["id"], (playlist.get("external_urls") or {}).get("spotify")
    print(f"  Playlist {playlist_id}: {url}")
    items_url = f"{API_URL}/playlists/{playlist_id}/items"
    added = http.post(items_url, json={"uris": [uri]}, headers=headers)
    if "snapshot_id" not in expect(added, 201, "6 add items"):
        raise SpikeError(f"6 add items: no snapshot_id; delete {url} manually")
    # Spotify has no hard delete: removing the playlist from the library is the closest thing.
    # The endpoint needs scopes the app does not request, so a 403 is expected and harmless.
    params = {"uris": f"spotify:playlist:{playlist_id}"}
    cleanup = http.delete(f"{API_URL}/me/library", params=params, headers=headers)
    if cleanup.status_code == 200:
        print("PASS 7 cleanup")
    else:
        print(f"INFO 7 cleanup: HTTP {cleanup.status_code}; remove {url} in the Spotify app")


def run_spike(http: httpx.Client, env: dict[str, str]) -> None:
    """Run steps 1-7 in order; a failing step among 1-6 raises SpikeError.

    Args:
        http: HTTP client.
        env: Spotify settings (the secret from `.env`, the rest from config/base.toml).
    """
    uri = search_step(http, env)
    headers = {"Authorization": f"Bearer {authorize_user(http, env)}"}
    me = http.get(f"{API_URL}/me", headers=headers)
    if me.status_code == 403:
        raise SpikeError("4 profile: HTTP 403, the account is not in the app's allowlist")
    print(f"  Logged in as {expect(me, 200, '4 profile').get('display_name')}")
    playlist_steps(http, headers, uri)


def main() -> int:
    """Load the Spotify settings, run the spike and print the outcome.

    Returns:
        Process exit code: 0 when steps 1-6 pass, 1 otherwise.
    """
    load_dotenv()
    with CONFIG_FILE.open("rb") as file:
        spotify = tomllib.load(file).get("spotify", {})
    env = {
        "SPOTIFY_CLIENT_ID": str(spotify.get("client_id", "")).strip(),
        "SPOTIFY_CLIENT_SECRET": os.getenv("SPOTIFY_CLIENT_SECRET", "").strip(),
        "SPOTIFY_REDIRECT_URI": str(spotify.get("redirect_uri", "")).strip(),
        "SPOTIFY_MARKET": str(spotify.get("market", "")).strip() or "IT",
    }
    missing = [name for name, value in env.items() if not value]
    if missing:
        print(f"FAIL 0 settings: missing {', '.join(missing)} (.env or config/base.toml)")
        return 1
    try:
        with httpx.Client(timeout=TIMEOUT_S) as http:
            run_spike(http, env)
    except (SpikeError, httpx.HTTPError, ValueError) as exc:  # ValueError: non-JSON body
        print(f"FAIL {exc}")
        return 1
    print("Spike passed: steps 1-6 OK, Phase 3b can start.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
