"""Environment loading, validation and application-wide constants."""

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

PLAYLIST_MIN_SIZE = 1  # Smallest playlist the app builds (fixed, not configurable)
PLAYLIST_HARD_MAX_SIZE = 30  # Absolute size cap: PLAYLIST_MAX_SIZE may lower it, never raise it
OVERGENERATION_RATIO = 0.2  # Extra LLM candidates per requested track, absorbing not-found ones
MAX_STORED_MESSAGES = 50  # Messages kept per session document (Firestore 1 MiB limit)
SESSION_ID_STORAGE_KEY = "apg_session_id"  # localStorage key holding the session id
SPOTIFY_SCOPE = "playlist-modify-private"  # The only OAuth scope the app requests

REQUIRED_VARS = (  # Variables that must be set and non-empty
    "GOOGLE_API_KEY",
    "GCP_PROJECT_ID",
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    "SPOTIFY_REDIRECT_URI",
    "SESSION_ENCRYPTION_KEY",
)
OPTIONAL_DEFAULTS = {  # Optional variables and the value used when unset or empty
    "SESSIONS_COLLECTION": "sessions",
    "SESSION_TTL_MINUTES": "60",
    "LLM_MODEL": "gemini-3.5-flash-lite",
    "INTENT_MODEL": "gemma-4-26b-a4b-it",
    "SPOTIFY_MARKET": "IT",
    "PLAYLIST_DEFAULT_SIZE": "16",
    "PLAYLIST_MAX_SIZE": str(PLAYLIST_HARD_MAX_SIZE),
    "RATE_LIMIT_MAX_REQUESTS": "12",
    "RATE_LIMIT_WINDOW": "60",
    "CLOUD_RUN_URL": "",
}
ENV_VARS = REQUIRED_VARS + tuple(OPTIONAL_DEFAULTS)  # All 16 variables the app reads
# Spotify accepts HTTPS anywhere, but plain HTTP only on a loopback IP literal (never localhost).
REDIRECT_URI_PATTERN = re.compile(r"https://[^/?#\s]+(/\S*)?|http://127\.0\.0\.1:\d{1,5}/\S*")


class ConfigError(RuntimeError):
    """Raised when the environment is missing variables or holds invalid values."""


@dataclass(frozen=True)
class Settings:
    """Typed, validated view of the environment; secrets are excluded from repr()."""

    google_api_key: str = field(repr=False)
    gcp_project_id: str
    spotify_client_id: str
    spotify_client_secret: str = field(repr=False)
    spotify_redirect_uri: str
    session_encryption_key: str = field(repr=False)
    sessions_collection: str
    session_ttl_minutes: int
    llm_model: str
    intent_model: str
    spotify_market: str
    playlist_default_size: int
    playlist_max_size: int
    rate_limit_max_requests: int
    rate_limit_window: int
    cloud_run_url: str | None


def _validate(settings: Settings) -> list[str]:
    """Check cross-field rules: size ordering, positive limits and the redirect URI.

    Args:
        settings: Settings built from the environment.

    Returns:
        Human-readable validation errors, empty when the settings are valid.
    """
    errors = []
    default, maximum = settings.playlist_default_size, settings.playlist_max_size
    if not PLAYLIST_MIN_SIZE <= default <= maximum <= PLAYLIST_HARD_MAX_SIZE:
        errors.append(
            f"playlist sizes must satisfy {PLAYLIST_MIN_SIZE} <= PLAYLIST_DEFAULT_SIZE "
            f"<= PLAYLIST_MAX_SIZE <= {PLAYLIST_HARD_MAX_SIZE}, got {default} and {maximum}"
        )
    positives = ("session_ttl_minutes", "rate_limit_max_requests", "rate_limit_window")
    errors.extend(f"{n.upper()} must be positive" for n in positives if getattr(settings, n) < 1)
    if not REDIRECT_URI_PATTERN.fullmatch(settings.spotify_redirect_uri):
        errors.append(
            "SPOTIFY_REDIRECT_URI must be https://... or http://127.0.0.1:<port>/... "
            f"(Spotify rejects localhost), got {settings.spotify_redirect_uri!r}"
        )
    return errors


def _int(env: dict[str, str], name: str) -> int:
    """Parse an integer variable.

    Args:
        env: Stripped values of all variables.
        name: Environment variable name.

    Returns:
        The parsed integer.
    """
    try:
        return int(env[name])
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {env[name]!r}") from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load `.env`, then read and validate every variable (cached after the first call).

    Settings are read lazily (never at import time), so tests and CI run without a `.env`.

    Returns:
        The validated application settings.
    """
    load_dotenv()
    env = {name: os.getenv(name, "").strip() for name in ENV_VARS}
    missing = [name for name in REQUIRED_VARS if not env[name]]
    if missing:
        raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")
    env |= {name: env[name] or default for name, default in OPTIONAL_DEFAULTS.items()}
    settings = Settings(
        google_api_key=env["GOOGLE_API_KEY"],
        gcp_project_id=env["GCP_PROJECT_ID"],
        spotify_client_id=env["SPOTIFY_CLIENT_ID"],
        spotify_client_secret=env["SPOTIFY_CLIENT_SECRET"],
        spotify_redirect_uri=env["SPOTIFY_REDIRECT_URI"],
        session_encryption_key=env["SESSION_ENCRYPTION_KEY"],
        sessions_collection=env["SESSIONS_COLLECTION"],
        session_ttl_minutes=_int(env, "SESSION_TTL_MINUTES"),
        llm_model=env["LLM_MODEL"],
        intent_model=env["INTENT_MODEL"],
        spotify_market=env["SPOTIFY_MARKET"],
        playlist_default_size=_int(env, "PLAYLIST_DEFAULT_SIZE"),
        playlist_max_size=_int(env, "PLAYLIST_MAX_SIZE"),
        rate_limit_max_requests=_int(env, "RATE_LIMIT_MAX_REQUESTS"),
        rate_limit_window=_int(env, "RATE_LIMIT_WINDOW"),
        cloud_run_url=env["CLOUD_RUN_URL"] or None,
    )
    errors = _validate(settings)
    if errors:
        raise ConfigError("Invalid configuration: " + "; ".join(errors))
    return settings
