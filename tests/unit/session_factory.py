"""Shared builders for session-related unit tests."""

from datetime import UTC, datetime, timedelta
from typing import Any

from src.schema import ChatMessage, SessionState

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)  # Frozen clock used by session tests
SID = "8c5a3f2e-1b4d-4c6e-9f0a-2d3b4c5d6e7f"  # Fake canonical UUID4 session id


def make_state(messages: int = 0, **fields: Any) -> SessionState:
    """Build a guest session created one minute before NOW, expiring in an hour.

    Args:
        messages: Number of alternating user/assistant messages, contents "m0", "m1"...
        **fields: Field overrides.

    Returns:
        The session state.
    """
    then = NOW - timedelta(minutes=1)
    history = [
        ChatMessage(role="user" if i % 2 == 0 else "assistant", content=f"m{i}", created_at=then)
        for i in range(messages)
    ]
    base = {"created_at": then, "last_message_at": then, "expires_at": then + timedelta(hours=1)}
    return SessionState(session_id=SID, mode="guest", messages=history, **(base | fields))
