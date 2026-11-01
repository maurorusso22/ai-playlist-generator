"""Validated, non-secret application settings, read from the TOML configuration files."""

import re
from functools import lru_cache
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from src.config.constants import PLAYLIST_HARD_MAX_SIZE, PLAYLIST_MIN_SIZE
from src.config.errors import ConfigError
from src.config.files import load_config

# Spotify accepts HTTPS anywhere, but plain HTTP only on a loopback IP literal (never localhost).
REDIRECT_URI_PATTERN = re.compile(r"https://[^/?#\s]+(/\S*)?|http://127\.0\.0\.1:\d{1,5}/\S*")

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]  # Non-blank string
Size = Annotated[int, Field(ge=PLAYLIST_MIN_SIZE, le=PLAYLIST_HARD_MAX_SIZE)]  # Playlist size


class _Section(BaseModel):
    """Base of every section: immutable, strict types (no "16" for 16), unknown keys rejected."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class GcpConfig(_Section):
    """[gcp]: the Google Cloud project hosting Firestore."""

    project_id: Text


class SessionsConfig(_Section):
    """[sessions]: chat sessions stored in Firestore."""

    collection: Text
    ttl_minutes: PositiveInt


class ModelConfig(_Section):
    """[llm] and [intent_gate]: a Google AI Studio model id."""

    model: Text


class SpotifyConfig(_Section):
    """[spotify]: the non-secret half of the Spotify app and the catalog market."""

    client_id: Text
    redirect_uri: Text
    market: Annotated[str, Field(pattern=r"^[A-Z]{2}$")]

    @field_validator("redirect_uri")
    @classmethod
    def _check_redirect_uri(cls, uri: str) -> str:
        """Enforce Spotify's redirect URI rules.

        Args:
            uri: The configured redirect URI.

        Returns:
            The URI, unchanged.
        """
        if not REDIRECT_URI_PATTERN.fullmatch(uri):
            raise ValueError("must be https://... or http://127.0.0.1:<port>/... (never localhost)")
        return uri


class PlaylistConfig(_Section):
    """[playlist]: default and maximum size, both within the fixed hard bounds."""

    default_size: Size
    max_size: Size

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        """Keep the default size within the configured maximum.

        Returns:
            The validated section.
        """
        if self.default_size > self.max_size:
            raise ValueError("default_size must not exceed max_size")
        return self


class RateLimitConfig(_Section):
    """[rate_limit]: per-IP sliding window of chat messages."""

    max_requests: PositiveInt
    window: PositiveInt


class Settings(_Section):
    """Every non-secret setting, one attribute per TOML section."""

    gcp: GcpConfig
    sessions: SessionsConfig
    llm: ModelConfig
    intent_gate: ModelConfig
    spotify: SpotifyConfig
    playlist: PlaylistConfig
    rate_limit: RateLimitConfig


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Read and validate the configuration files (cached after the first call).

    Settings are read lazily (never at import time), so importing a module needs no config.

    Returns:
        The validated application settings.
    """
    try:
        return Settings.model_validate(load_config())
    except ValidationError as exc:
        errors = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise ConfigError(f"Invalid configuration: {errors}") from None
