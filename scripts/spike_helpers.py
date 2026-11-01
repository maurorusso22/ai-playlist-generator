"""HTTP and OAuth helpers for the dev-only Spotify spike (`scripts/spotify_spike.py`).

Standalone like the spike itself: httpx only, no `src/` imports. Tokens are kept in memory
and never printed.
"""

import secrets
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

TOKEN_URL = "https://accounts.spotify.com/api/token"  # noqa: S105 - OAuth token endpoint URL
AUTHORIZE_URL = "https://accounts.spotify.com/authorize"  # OAuth consent page
SCOPE = "playlist-modify-private"  # The only scope the app requests
STATE_BYTES = 32  # Random bytes in the OAuth `state`


class SpikeError(Exception):
    """A spike step failed; the message is printed as its FAIL line."""


def expect(response: httpx.Response, status: int, step: str) -> dict[str, Any]:
    """Check a response status, printing PASS or raising with Spotify's error message.

    Args:
        response: Response of the step's request.
        status: Expected HTTP status.
        step: Step label used in the PASS/FAIL line.

    Returns:
        The decoded JSON body ({} when empty).
    """
    body = response.json() if response.content else {}
    if response.status_code != status:
        error = body.get("error") if isinstance(body, dict) else None
        detail = error.get("message") if isinstance(error, dict) else body.get("error_description")
        raise SpikeError(f"{step}: HTTP {response.status_code} {detail or error or ''}")
    print(f"PASS {step}")
    return body


def token(http: httpx.Client, env: dict[str, str], data: dict[str, str], step: str) -> str:
    """Call the token endpoint with HTTP Basic client credentials.

    Args:
        http: HTTP client.
        env: Spotify settings (the secret from `.env`, the rest from config/base.toml).
        data: Grant form fields.
        step: Step label used in the PASS/FAIL line.

    Returns:
        The access token (kept in memory only).
    """
    credentials = (env["SPOTIFY_CLIENT_ID"], env["SPOTIFY_CLIENT_SECRET"])
    response = http.post(TOKEN_URL, data=data, auth=credentials)
    return str(expect(response, 200, step)["access_token"])


def authorize_user(http: httpx.Client, env: dict[str, str]) -> str:
    """Print the consent URL, read the pasted callback URL, verify `state`, exchange the code.

    `show_dialog=true` forces the consent screen even when the user already approved the app.

    Args:
        http: HTTP client.
        env: Spotify settings (the secret from `.env`, the rest from config/base.toml).

    Returns:
        The user's access token (kept in memory only).
    """
    state, redirect_uri = secrets.token_urlsafe(STATE_BYTES), env["SPOTIFY_REDIRECT_URI"]
    params = {"client_id": env["SPOTIFY_CLIENT_ID"], "response_type": "code", "scope": SCOPE}
    params |= {"redirect_uri": redirect_uri, "state": state, "show_dialog": "true"}
    print(f"\nOpen with the allowlisted account:\n{AUTHORIZE_URL}?{urlencode(params)}")
    print("After consent the browser lands on the redirect URI; the page may fail to load.")
    query = parse_qs(urlparse(input("Paste the full redirect URL: ").strip()).query)
    if "error" in query:
        raise SpikeError(f"3 authorize: Spotify returned error={query['error'][0]}")
    if not secrets.compare_digest(state.encode(), query.get("state", [""])[0].encode()):
        raise SpikeError("3 authorize: state mismatch, the URL is not from this run")
    code = query.get("code", [""])[0]
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
    return token(http, env, data, "3 authorization code exchange")
