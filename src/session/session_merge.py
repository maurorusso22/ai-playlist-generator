"""Session-state rules: sliding expiry, field validation, message cap and index rebasing.

Kept apart from `session_store.py` so the Firestore layer stays small and this logic is
testable without any client.
"""

from datetime import datetime, timedelta
from typing import Any

from src.config.constants import MAX_STORED_MESSAGES
from src.config.settings import get_settings
from src.models.session.chat_message import ChatMessage
from src.models.session.pending_action import PendingAction
from src.models.session.session_state import SessionState

IMMUTABLE_FIELDS = frozenset({"session_id", "created_at"})  # Never rewritten by update()
MANAGED_FIELDS = frozenset({"messages", "last_message_at", "expires_at"})  # Set by the store
MUTABLE_FIELDS = (  # Fields callers may change through save_turn()/touch()
    frozenset(SessionState.model_fields) - IMMUTABLE_FIELDS - MANAGED_FIELDS
)


def expiry(now: datetime) -> datetime:
    """Compute the sliding expiry: `now` plus `sessions.ttl_minutes`.

    Args:
        now: Time of the latest activity (a message or a confirmation click).

    Returns:
        The new `expires_at`.
    """
    return now + timedelta(minutes=get_settings().sessions.ttl_minutes)


def _shift(index: int | None, dropped: int) -> int | None:
    """Rebase a message index after the oldest messages were trimmed.

    Args:
        index: Index into the untrimmed message list, or None.
        dropped: Number of messages removed from the front.

    Returns:
        The rebased index, or None when the referenced message was dropped.
    """
    return None if index is None or index < dropped else index - dropped


def _rebase_action(action: PendingAction | None, dropped: int) -> PendingAction | None:
    """Rebase the pending action's message index.

    Args:
        action: The pending action, or None.
        dropped: Number of messages removed from the front.

    Returns:
        The rebased action, or None when its message was dropped.
    """
    if action is None:
        return None
    index = _shift(action.message_index, dropped)
    return None if index is None else PendingAction(kind=action.kind, message_index=index)


def merge_state(state: SessionState, messages: list[ChatMessage], **fields: Any) -> SessionState:
    """Validate changes, apply them and cap the history at MAX_STORED_MESSAGES.

    Callers compute message indexes on the untrimmed list; they are rebased here by the number
    of dropped messages, and cleared when the message they point to was dropped.

    Args:
        state: The cached session state.
        messages: The full, untrimmed message list.
        **fields: Field changes, including the store-managed timestamps.

    Returns:
        The new, validated session state.
    """
    unknown = set(fields) - MUTABLE_FIELDS - MANAGED_FIELDS
    if unknown:
        raise ValueError(f"Unknown or read-only session fields: {sorted(unknown)}")
    merged: SessionState = SessionState.model_validate(
        dict(state) | fields | {"messages": messages}
    )
    dropped = max(0, len(messages) - MAX_STORED_MESSAGES)
    if not dropped:
        return merged
    trimmed: SessionState = merged.model_copy(
        update={
            "messages": merged.messages[dropped:],
            "draft_message_index": _shift(merged.draft_message_index, dropped),
            "pending_action": _rebase_action(merged.pending_action, dropped),
        }
    )
    return trimmed
