"""Live Firestore session lifecycle against the throwaway `sessions_test` collection.

Requires a complete `config/base.toml` and Application Default Credentials
(`gcloud auth application-default login`); no secret is needed. Created documents are
deleted in teardown.
"""

import os
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from src import session_store
from src.config.errors import ConfigError
from src.config.files import load_config
from src.config.settings import get_settings
from src.schema import ChatMessage

TEST_COLLECTION = "sessions_test"  # Collection used instead of the real one


def _adc_available() -> bool:
    """Check for ADC without contacting any metadata server.

    Returns:
        True when a credentials file is configured or gcloud's ADC file exists.
    """
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        return True
    config_dir = Path(os.getenv("CLOUDSDK_CONFIG") or Path.home() / ".config" / "gcloud")
    return (config_dir / "application_default_credentials.json").is_file()


pytestmark = pytest.mark.skipif(
    not _adc_available(), reason="Requires Application Default Credentials"
)


@pytest.fixture
def created(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Point the store at the test collection and delete created sessions afterwards.

    Skips the test when `config/base.toml` is incomplete (e.g. a blank `gcp.project_id`).

    Args:
        monkeypatch: Pytest fixture used to patch the configuration loader.

    Returns:
        A list the tests append created session ids to.
    """
    sections = load_config()
    sections["sessions"]["collection"] = TEST_COLLECTION
    monkeypatch.setattr("src.config.settings.load_config", lambda *_: sections)
    get_settings.cache_clear()
    try:
        get_settings()
    except ConfigError as exc:
        pytest.skip(f"Firestore tests require a complete config/base.toml: {exc}")
    session_store._client.cache_clear()
    ids: list[str] = []
    yield ids
    for session_id in ids:
        session_store.delete_session(session_id)
    get_settings.cache_clear()


def test_create_save_load_round_trip(created: list[str]) -> None:
    state = session_store.create_session("guest")
    created.append(state.session_id)
    messages = [
        ChatMessage(role="user", content="90s rock"),
        ChatMessage(role="assistant", content="Ok"),
    ]
    session_store.save_turn(state, messages)
    status, loaded = session_store.load_session(state.session_id)
    assert status == "active" and loaded is not None
    assert [m.content for m in loaded.messages] == ["90s rock", "Ok"]
    assert loaded.expires_at.tzinfo is not None


def test_expired_session_is_deleted_on_read(
    created: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    state = session_store.create_session("guest")
    created.append(state.session_id)
    real_now = session_store._now()
    ttl = timedelta(minutes=get_settings().sessions.ttl_minutes)
    monkeypatch.setattr(session_store, "_now", lambda: real_now - ttl - timedelta(minutes=1))
    session_store.touch(state)
    monkeypatch.setattr(session_store, "_now", lambda: real_now)
    assert session_store.load_session(state.session_id) == ("expired", None)
    assert session_store.load_session(state.session_id) == ("missing", None)


def test_delete_session_removes_document(created: list[str]) -> None:
    state = session_store.create_session("guest")
    created.append(state.session_id)
    session_store.delete_session(state.session_id)
    assert session_store.load_session(state.session_id) == ("missing", None)
