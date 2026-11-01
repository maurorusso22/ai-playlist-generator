"""Unit tests for src/session_store.py with the Firestore client mocked and the clock frozen."""

from collections.abc import Iterator
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from src import session_store
from src.crypto import encrypt_tokens
from src.models.conversation.playlist_draft import PlaylistDraft
from src.models.session.chat_message import ChatMessage
from src.models.session.pending_action import PendingAction
from src.models.spotify.resolved_track import ResolvedTrack
from src.models.spotify.spotify_tokens import SpotifyTokens
from tests.unit.session_factory import NOW, SID
from tests.unit.session_factory import make_state as _state


@pytest.fixture
def collection(mocker: MockerFixture) -> Iterator[MagicMock]:
    """Patch firestore.Client and freeze `_now`.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        The mocked sessions CollectionReference.
    """
    session_store._client.cache_clear()
    client_cls = mocker.patch("src.session_store.firestore.Client")
    mocker.patch("src.session_store._now", return_value=NOW)
    yield client_cls.return_value.collection.return_value
    session_store._client.cache_clear()


@pytest.fixture
def doc(collection: MagicMock) -> MagicMock:
    """The DocumentReference mock returned for every session id.

    Args:
        collection: The mocked sessions collection.

    Returns:
        The document mock.
    """
    document: MagicMock = collection.document.return_value
    return document


def test_create_session_writes_aware_expiry(doc: MagicMock) -> None:
    state = session_store.create_session("guest")
    written = doc.set.call_args.args[0]
    assert written["expires_at"] == NOW + timedelta(minutes=60)
    assert written["expires_at"].tzinfo is not None
    assert state.mode == "guest" and len(state.session_id) == 36


def test_load_missing(doc: MagicMock) -> None:
    doc.get.return_value.exists = False
    assert session_store.load_session(SID) == ("missing", None)


def test_load_expired_deletes_document(collection: MagicMock, doc: MagicMock) -> None:
    doc.get.return_value.to_dict.return_value = _state(expires_at=NOW).model_dump()
    assert session_store.load_session(SID) == ("expired", None)
    collection.document.assert_called_with(SID)
    doc.delete.assert_called_once()


def test_load_active(doc: MagicMock) -> None:
    doc.get.return_value.to_dict.return_value = _state(messages=3).model_dump()
    status, state = session_store.load_session(SID)
    assert status == "active" and state is not None and len(state.messages) == 3
    doc.delete.assert_not_called()


def test_load_unreadable_document_is_deleted_as_missing(doc: MagicMock) -> None:
    doc.get.return_value.to_dict.return_value = {"session_id": SID, "mode": "unknown"}
    assert session_store.load_session(SID) == ("missing", None)
    doc.delete.assert_called_once()


def test_save_turn_single_update_with_slid_expiry(doc: MagicMock) -> None:
    draft = PlaylistDraft(title="T", description="D", target_size=1, tracks=[])
    track = ResolvedTrack(name="Animals", artists=["Martin Garrix"], found=False)
    action = PendingAction(kind="login_to_save", message_index=1)
    reply = [ChatMessage(role="user", content="hi"), ChatMessage(role="assistant", content="ok")]
    state = session_store.save_turn(
        _state(), reply, draft=draft, resolved_tracks=[track], pending_action=action
    )
    doc.update.assert_called_once()
    payload = doc.update.call_args.args[0]
    for key in ("messages", "draft", "resolved_tracks", "pending_action", "last_message_at"):
        assert key in payload
    assert payload["last_message_at"] == NOW
    assert payload["expires_at"] == NOW + timedelta(minutes=60)
    assert len(payload["messages"]) == 2 and payload["draft"]["title"] == "T"
    assert "session_id" not in payload and "created_at" not in payload
    assert state.pending_action == action


def test_save_turn_trims_to_cap_and_shifts_indexes(doc: MagicMock) -> None:
    new = [ChatMessage(role="user", content="u"), ChatMessage(role="assistant", content="a")]
    action = PendingAction(kind="confirm_create", message_index=59)
    state = session_store.save_turn(
        _state(messages=58), new, pending_action=action, draft_message_index=59
    )
    assert len(state.messages) == 50 and state.messages[0].content == "m10"
    assert state.pending_action is not None and state.pending_action.message_index == 49
    assert state.draft_message_index == 49
    assert doc.update.call_args.args[0]["pending_action"]["message_index"] == 49


def test_touch_slides_expiry_and_keeps_last_message(doc: MagicMock) -> None:
    before = _state(messages=2)
    state = session_store.touch(before, pending_action=None)
    doc.update.assert_called_once()
    assert state.expires_at == NOW + timedelta(minutes=60)
    assert state.last_message_at == before.last_message_at


def test_delete_session_deletes_right_document(collection: MagicMock, doc: MagicMock) -> None:
    session_store.delete_session(SID)
    collection.document.assert_called_with(SID)
    doc.delete.assert_called_once()


def test_is_expired_uses_local_state(doc: MagicMock) -> None:
    assert session_store.is_expired(_state(expires_at=NOW))
    assert not session_store.is_expired(_state(expires_at=NOW + timedelta(seconds=1)))
    doc.get.assert_not_called()


def test_payload_never_contains_plaintext_tokens(doc: MagicMock) -> None:
    secret = SpotifyTokens(access_token="acc-SECRET", refresh_token="ref-SECRET", expires_at=NOW)
    blob = encrypt_tokens(secret)
    session_store.touch(_state(), mode="spotify", spotify_auth=blob)
    payload = doc.update.call_args.args[0]
    assert "acc-SECRET" not in repr(payload) and "ref-SECRET" not in repr(payload)
    assert payload["spotify_auth"] == blob
