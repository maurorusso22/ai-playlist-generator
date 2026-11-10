"""Unit tests for src/config/secrets.py (secrets read only from the environment)."""

import pytest

from src.config.errors import ConfigError
from src.config.secrets import OPTIONAL_SECRET_VARS, SECRET_VARS, get_secrets


def test_missing_secrets_are_reported_together(monkeypatch: pytest.MonkeyPatch) -> None:
    """One ConfigError names every missing secret."""
    monkeypatch.delenv("GOOGLE_API_KEY")
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET")
    with pytest.raises(ConfigError) as exc_info:
        get_secrets()
    assert "GOOGLE_API_KEY" in str(exc_info.value)
    assert "SPOTIFY_CLIENT_SECRET" in str(exc_info.value)


def test_blank_secret_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A whitespace-only secret is reported as missing."""
    monkeypatch.setenv("SESSION_ENCRYPTION_KEY", "  ")
    with pytest.raises(ConfigError, match="SESSION_ENCRYPTION_KEY"):
        get_secrets()


def test_secrets_are_read(fake_secrets: dict[str, str]) -> None:
    """Every secret is copied from the environment unchanged."""
    secrets = get_secrets()
    assert secrets.google_api_key == fake_secrets["GOOGLE_API_KEY"]
    assert secrets.spotify_client_secret == fake_secrets["SPOTIFY_CLIENT_SECRET"]
    assert secrets.session_encryption_key == fake_secrets["SESSION_ENCRYPTION_KEY"]
    assert secrets.anthropic_api_key == fake_secrets["ANTHROPIC_API_KEY"]


def test_anthropic_key_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing ANTHROPIC_API_KEY is not an error here: the Claude engine checks it on use."""
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert get_secrets().anthropic_api_key == ""


def test_secrets_are_cached_and_hidden_from_repr(fake_secrets: dict[str, str]) -> None:
    """get_secrets is cached and repr() never shows a secret value."""
    secrets = get_secrets()
    assert get_secrets() is secrets
    for name in SECRET_VARS + OPTIONAL_SECRET_VARS:
        assert fake_secrets[name] not in repr(secrets)
