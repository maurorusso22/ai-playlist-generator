"""Unit tests for src/session/session_merge.py (pure session-state rules, no Firestore)."""

from datetime import timedelta

import pytest

from src.config.files import Sections
from src.config.settings import get_settings
from src.models.session.chat_message import ChatMessage
from src.models.session.pending_action import PendingAction
from src.session.session_merge import MUTABLE_FIELDS, expiry, merge_state
from tests.unit.session_factory import NOW, make_state


def test_expiry_uses_configured_ttl(config: Sections) -> None:
    assert expiry(NOW) == NOW + timedelta(minutes=60)
    config["sessions"]["ttl_minutes"] = 2
    get_settings.cache_clear()
    assert expiry(NOW) == NOW + timedelta(minutes=2)


def test_under_cap_keeps_everything() -> None:
    state = make_state(messages=10)
    action = PendingAction(kind="confirm_create", message_index=9)
    merged = merge_state(state, list(state.messages), pending_action=action)
    assert len(merged.messages) == 10 and merged.pending_action == action


def test_index_zero_after_trim_is_kept() -> None:
    state = make_state(messages=50)
    new = [ChatMessage(role="user", content="u")]
    action = PendingAction(kind="login_to_save", message_index=1)
    merged = merge_state(state, [*state.messages, *new], pending_action=action)
    assert merged.pending_action is not None and merged.pending_action.message_index == 0


def test_indexes_of_dropped_messages_are_cleared() -> None:
    state = make_state(messages=58)
    new = [ChatMessage(role="user", content="u")] * 2
    action = PendingAction(kind="confirm_create", message_index=3)
    merged = merge_state(
        state, [*state.messages, *new], pending_action=action, draft_message_index=0
    )
    assert merged.pending_action is None and merged.draft_message_index is None


def test_changes_are_validated() -> None:
    with pytest.raises(ValueError, match="mode"):
        merge_state(make_state(), [], mode="admin")


@pytest.mark.parametrize("field", ["session_id", "created_at", "nope"])
def test_read_only_or_unknown_fields_are_rejected(field: str) -> None:
    with pytest.raises(ValueError, match="read-only"):
        merge_state(make_state(), [], **{field: "x"})


def test_mutable_fields_cover_phase_six_needs() -> None:
    expected = {"mode", "draft", "draft_message_index", "resolved_tracks", "pending_action"}
    assert expected | {"created_playlist", "oauth_state", "spotify_auth"} == MUTABLE_FIELDS
