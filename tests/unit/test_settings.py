"""Unit tests for src/config/settings.py (validation of the non-secret configuration)."""

import re
from typing import Any

import pytest

from src.config.errors import ConfigError
from src.config.files import Sections
from src.config.settings import get_settings


def _set(config: Sections, key: str, value: Any) -> None:
    """Change one dotted setting and drop the cached settings.

    Args:
        config: The sections served to `get_settings` (the `config` fixture).
        key: Dotted key, e.g. "playlist.max_size".
        value: The new value.
    """
    section, name = key.split(".")
    config[section][name] = value
    get_settings.cache_clear()


def test_committed_base_values() -> None:
    """config/base.toml holds the documented values."""
    settings = get_settings()
    assert settings.sessions.collection == "sessions"
    assert settings.sessions.ttl_minutes == 60
    assert settings.llm.model == "gemini-3.5-flash-lite"
    assert settings.intent_gate.model == "gemma-4-26b-a4b-it"
    assert settings.spotify.market == "IT"
    assert settings.spotify.redirect_uri == "http://127.0.0.1:8501/"
    assert (settings.playlist.default_size, settings.playlist.max_size) == (16, 30)
    assert (settings.rate_limit.max_requests, settings.rate_limit.window) == (12, 60)


def test_errors_are_reported_together_with_dotted_keys(config: Sections) -> None:
    """One ConfigError names every invalid key as section.key."""
    config["gcp"]["project_id"] = "  "
    _set(config, "spotify.client_id", "")
    with pytest.raises(ConfigError) as exc_info:
        get_settings()
    assert "gcp.project_id" in str(exc_info.value)
    assert "spotify.client_id" in str(exc_info.value)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("playlist.max_size", 31),
        ("playlist.default_size", 0),
        ("playlist.default_size", "16"),
        ("playlist.default_size", True),
        ("sessions.ttl_minutes", 0),
        ("rate_limit.window", -1),
        ("spotify.market", "it"),
    ],
)
def test_invalid_values_raise(config: Sections, key: str, value: Any) -> None:
    """Out-of-range sizes, non-integers (strings, booleans), non-positive limits are rejected."""
    _set(config, key, value)
    with pytest.raises(ConfigError, match=re.escape(key)):
        get_settings()


def test_default_size_above_max_size_raises(config: Sections) -> None:
    """playlist.default_size must not exceed playlist.max_size."""
    config["playlist"] |= {"default_size": 20, "max_size": 10}
    get_settings.cache_clear()
    with pytest.raises(ConfigError, match="default_size must not exceed max_size"):
        get_settings()


def test_max_size_can_be_lowered(config: Sections) -> None:
    """playlist.max_size may lower the cap below 30."""
    config["playlist"] |= {"default_size": 10, "max_size": 20}
    get_settings.cache_clear()
    playlist = get_settings().playlist
    assert (playlist.default_size, playlist.max_size) == (10, 20)


@pytest.mark.parametrize(
    ("section", "key", "location"),
    [("playlist", "maxsize", "playlist.maxsize"), ("secrets", "api_key", "secrets")],
)
def test_unknown_keys_and_sections_are_rejected(
    config: Sections, section: str, key: str, location: str
) -> None:
    """Typos and stray sections (a secret pasted into the config, say) are errors."""
    config.setdefault(section, {})[key] = "value"
    get_settings.cache_clear()
    with pytest.raises(ConfigError, match=re.escape(f"{location}: Extra inputs are not permitted")):
        get_settings()


def test_missing_section_is_reported(config: Sections) -> None:
    """A section removed from the file is reported by name."""
    del config["rate_limit"]
    get_settings.cache_clear()
    with pytest.raises(ConfigError, match="rate_limit: Field required"):
        get_settings()


@pytest.mark.parametrize(
    "uri",
    ["http://localhost:8501/", "http://127.0.0.1/", "http://example.com/", "ftp://127.0.0.1:21/"],
)
def test_rejected_redirect_uris(config: Sections, uri: str) -> None:
    """localhost, portless loopback and non-loopback HTTP URIs are rejected."""
    _set(config, "spotify.redirect_uri", uri)
    with pytest.raises(ConfigError, match=r"spotify\.redirect_uri"):
        get_settings()


@pytest.mark.parametrize("uri", ["http://127.0.0.1:8501/", "https://example.run.app/"])
def test_accepted_redirect_uris(config: Sections, uri: str) -> None:
    """Loopback HTTP with a port and any HTTPS URI are accepted."""
    _set(config, "spotify.redirect_uri", uri)
    assert get_settings().spotify.redirect_uri == uri


def test_settings_are_cached_and_immutable() -> None:
    """get_settings is cached and its sections cannot be changed at runtime."""
    settings = get_settings()
    assert get_settings() is settings
    with pytest.raises(ValueError, match="frozen"):
        settings.playlist.max_size = 5
