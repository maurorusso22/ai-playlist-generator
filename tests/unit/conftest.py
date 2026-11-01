"""Shared unit-test fixtures: an isolated, offline configuration for every test."""

from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet

from src.config import ENV_VARS, get_settings


@pytest.fixture(autouse=True)
def fake_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Replace the real environment with fake values for the six required variables.

    `load_dotenv` is patched to a no-op so a developer's real `.env` cannot re-populate
    variables a test unsets; the settings cache is cleared before and after each test.

    Args:
        monkeypatch: Pytest fixture used to patch the environment.

    Returns:
        The fake required variables, yielded so tests can read them (e.g. the Fernet key).
    """
    monkeypatch.setattr("src.config.load_dotenv", lambda *a, **k: False)
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    values = {
        "GOOGLE_API_KEY": "test-google-api-key",
        "GCP_PROJECT_ID": "test-project",
        "SPOTIFY_CLIENT_ID": "test-client-id",
        "SPOTIFY_CLIENT_SECRET": "test-client-secret",
        "SPOTIFY_REDIRECT_URI": "http://127.0.0.1:8501/",
        "SESSION_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    yield values
    get_settings.cache_clear()
