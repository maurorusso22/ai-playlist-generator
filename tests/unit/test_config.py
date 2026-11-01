"""Unit tests for src/config.py."""

import pytest

from src.config import ConfigError, get_settings


def test_missing_required_variables_are_reported_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One ConfigError names every missing required variable."""
    monkeypatch.delenv("GOOGLE_API_KEY")
    monkeypatch.delenv("SPOTIFY_CLIENT_ID")
    with pytest.raises(ConfigError) as exc_info:
        get_settings()
    assert "GOOGLE_API_KEY" in str(exc_info.value)
    assert "SPOTIFY_CLIENT_ID" in str(exc_info.value)


def test_empty_required_variable_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank required variable is reported as missing."""
    monkeypatch.setenv("GCP_PROJECT_ID", "  ")
    with pytest.raises(ConfigError, match="GCP_PROJECT_ID"):
        get_settings()


def test_optional_variables_use_defaults() -> None:
    """Unset optional variables fall back to the documented defaults."""
    settings = get_settings()
    assert settings.sessions_collection == "sessions"
    assert settings.session_ttl_minutes == 60
    assert settings.llm_model == "gemini-3.5-flash-lite"
    assert settings.intent_model == "gemma-4-26b-a4b-it"
    assert settings.spotify_market == "IT"
    assert settings.playlist_default_size == 16
    assert settings.playlist_max_size == 30
    assert settings.rate_limit_max_requests == 12
    assert settings.rate_limit_window == 60
    assert settings.cloud_run_url is None


def test_required_values_are_read(fake_env: dict[str, str]) -> None:
    """Required variables are copied into the settings unchanged."""
    settings = get_settings()
    assert settings.google_api_key == fake_env["GOOGLE_API_KEY"]
    assert settings.session_encryption_key == fake_env["SESSION_ENCRYPTION_KEY"]
    assert settings.spotify_redirect_uri == "http://127.0.0.1:8501/"


@pytest.mark.parametrize(
    "overrides",
    [
        {"PLAYLIST_DEFAULT_SIZE": "20", "PLAYLIST_MAX_SIZE": "10"},
        {"PLAYLIST_MAX_SIZE": "31"},
        {"PLAYLIST_DEFAULT_SIZE": "0"},
        {"PLAYLIST_DEFAULT_SIZE": "sixteen"},
        {"SESSION_TTL_MINUTES": "0"},
    ],
)
def test_invalid_numeric_settings_raise(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, str]
) -> None:
    """Out-of-order sizes, sizes above 30, zero and non-integers are rejected."""
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError):
        get_settings()


def test_max_size_can_be_lowered(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLAYLIST_MAX_SIZE may lower the cap below 30."""
    monkeypatch.setenv("PLAYLIST_DEFAULT_SIZE", "10")
    monkeypatch.setenv("PLAYLIST_MAX_SIZE", "20")
    settings = get_settings()
    assert (settings.playlist_default_size, settings.playlist_max_size) == (10, 20)


@pytest.mark.parametrize(
    "uri",
    ["http://localhost:8501/", "http://127.0.0.1/", "http://example.com/", "ftp://127.0.0.1:21/"],
)
def test_rejected_redirect_uris(monkeypatch: pytest.MonkeyPatch, uri: str) -> None:
    """localhost, portless loopback and non-loopback HTTP URIs are rejected."""
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", uri)
    with pytest.raises(ConfigError, match="SPOTIFY_REDIRECT_URI"):
        get_settings()


@pytest.mark.parametrize("uri", ["http://127.0.0.1:8501/", "https://example.run.app/"])
def test_accepted_redirect_uris(monkeypatch: pytest.MonkeyPatch, uri: str) -> None:
    """Loopback HTTP with a port and any HTTPS URI are accepted."""
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", uri)
    assert get_settings().spotify_redirect_uri == uri


def test_settings_are_cached_and_hide_secrets(fake_env: dict[str, str]) -> None:
    """get_settings is cached and repr() never shows a secret."""
    settings = get_settings()
    assert get_settings() is settings
    for name in ("GOOGLE_API_KEY", "SPOTIFY_CLIENT_SECRET", "SESSION_ENCRYPTION_KEY"):
        assert fake_env[name] not in repr(settings)
