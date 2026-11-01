"""Shared unit-test fixtures: isolated, offline secrets and configuration for every test."""

import tomllib
from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet

from src.config.files import BASE_FILE, CONFIG_DIR, Sections
from src.config.secrets import get_secrets
from src.config.settings import get_settings

TEST_IDENTITY = {  # Values for the base.toml keys the repository leaves blank
    "gcp": {"project_id": "test-project"},
    "spotify": {"client_id": "test-client-id", "redirect_uri": "http://127.0.0.1:8501/"},
}


@pytest.fixture(autouse=True)
def fake_secrets(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Replace the real secrets with fake values.

    `load_dotenv` is patched to a no-op so a developer's real `.env` cannot re-populate
    secrets a test unsets; the secrets cache is cleared before and after each test.

    Args:
        monkeypatch: Pytest fixture used to patch the environment.

    Returns:
        The fake secrets, yielded so tests can read them (e.g. the Fernet key).
    """
    monkeypatch.setattr("src.config.secrets.load_dotenv", lambda *a, **k: False)
    values = {
        "GOOGLE_API_KEY": "test-google-api-key",
        "SPOTIFY_CLIENT_SECRET": "test-client-secret",
        "SESSION_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_secrets.cache_clear()
    yield values
    get_secrets.cache_clear()


@pytest.fixture(autouse=True)
def config(monkeypatch: pytest.MonkeyPatch) -> Iterator[Sections]:
    """Serve the committed config/base.toml, plus TEST_IDENTITY, to `get_settings`.

    Tests change a setting by assigning into the yielded sections and clearing the settings
    cache; the cache is also cleared before and after each test.

    Args:
        monkeypatch: Pytest fixture used to patch the configuration loader.

    Returns:
        The sections `get_settings` validates, yielded so tests can change them.
    """
    with (CONFIG_DIR / BASE_FILE).open("rb") as file:
        sections = tomllib.load(file)
    for name, values in TEST_IDENTITY.items():
        sections[name] |= values
    monkeypatch.setattr("src.config.settings.load_config", lambda *_: sections)
    get_settings.cache_clear()
    yield sections
    get_settings.cache_clear()
