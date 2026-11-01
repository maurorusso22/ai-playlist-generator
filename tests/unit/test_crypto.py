"""Unit tests for src/session/crypto.py (Fernet encryption of Spotify tokens)."""

from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet

from src.config.errors import ConfigError
from src.config.secrets import get_secrets
from src.models.spotify.spotify_tokens import SpotifyTokens
from src.session.crypto import decrypt_tokens, encrypt_tokens

ACCESS = "plain-access-token-123"  # Recognizable fake access token
REFRESH = "plain-refresh-token-456"  # Recognizable fake refresh token


@pytest.fixture
def tokens() -> SpotifyTokens:
    """Fake tokens with profile fields.

    Returns:
        A SpotifyTokens instance.
    """
    return SpotifyTokens(
        access_token=ACCESS,
        refresh_token=REFRESH,
        expires_at=datetime(2030, 1, 1, 12, 30, 15, 123456, tzinfo=UTC),
        user_id="user-1",
        display_name="Mauro",
    )


def _use_key(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    """Switch SESSION_ENCRYPTION_KEY and drop the cached secrets.

    Args:
        monkeypatch: Pytest fixture used to patch the environment.
        key: The new key value.
    """
    monkeypatch.setenv("SESSION_ENCRYPTION_KEY", key)
    get_secrets.cache_clear()


def test_round_trip_returns_equal_tokens(tokens: SpotifyTokens) -> None:
    restored = decrypt_tokens(encrypt_tokens(tokens))
    assert restored == tokens
    assert restored is not None
    assert restored.access_token.get_secret_value() == ACCESS
    assert restored.refresh_token.get_secret_value() == REFRESH
    assert restored.expires_at == tokens.expires_at


def test_ciphertext_does_not_contain_tokens(tokens: SpotifyTokens) -> None:
    blob = encrypt_tokens(tokens)
    assert ACCESS not in blob
    assert REFRESH not in blob
    assert "Mauro" not in blob


def test_different_key_returns_none(tokens: SpotifyTokens, monkeypatch: pytest.MonkeyPatch) -> None:
    blob = encrypt_tokens(tokens)
    _use_key(monkeypatch, Fernet.generate_key().decode())
    assert decrypt_tokens(blob) is None


def test_tampered_blob_returns_none(tokens: SpotifyTokens) -> None:
    assert decrypt_tokens("not-a-fernet-token") is None
    blob = encrypt_tokens(tokens)
    assert decrypt_tokens(blob[:-4] + "AAAA") is None


@pytest.mark.parametrize("key", ["not-a-key", "c2hvcnQ="])
def test_malformed_key_raises_config_error(
    tokens: SpotifyTokens, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    _use_key(monkeypatch, key)
    with pytest.raises(ConfigError, match="SESSION_ENCRYPTION_KEY"):
        encrypt_tokens(tokens)
    with pytest.raises(ConfigError):
        decrypt_tokens("anything")
