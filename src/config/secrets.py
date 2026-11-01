"""Secrets, read only from the environment: `.env` locally, Secret Manager on Cloud Run."""

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

from src.config.errors import ConfigError

SECRET_VARS = (  # Environment variables holding the secrets, all required
    "GOOGLE_API_KEY",
    "SPOTIFY_CLIENT_SECRET",
    "SESSION_ENCRYPTION_KEY",
)


@dataclass(frozen=True)
class Secrets:
    """The app's secrets; every field is excluded from repr() so none can leak into logs."""

    google_api_key: str = field(repr=False)
    spotify_client_secret: str = field(repr=False)
    session_encryption_key: str = field(repr=False)


@lru_cache(maxsize=1)
def get_secrets() -> Secrets:
    """Load `.env` when present, then read every secret (cached after the first call).

    Secrets are read lazily (never at import time), so tests and CI run without a `.env`.

    Returns:
        The secrets.
    """
    load_dotenv()
    values = {name: os.getenv(name, "").strip() for name in SECRET_VARS}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ConfigError(f"Missing required secrets (set them in .env): {', '.join(missing)}")
    return Secrets(**{name.lower(): value for name, value in values.items()})
