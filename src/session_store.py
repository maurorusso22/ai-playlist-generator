"""Firestore session CRUD: sliding expiry enforced on read (TTL is only garbage collection).

Datetimes are timezone-aware UTC so Firestore stores Timestamps; every mutation is one write.
"""

import logging
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Literal

from google.cloud import firestore
from pydantic import ValidationError

from src.config import get_settings
from src.schema import ChatMessage, SessionState
from src.session_merge import IMMUTABLE_FIELDS, expiry, merge_state

SessionStatus = Literal["active", "missing", "expired"]  # Outcome of load_session()


def _now() -> datetime:
    """Current time; patched in tests to freeze the clock.

    Returns:
        The current timezone-aware UTC datetime.
    """
    return datetime.now(UTC)


@lru_cache(maxsize=1)
def _client(project: str) -> firestore.Client:
    """Create the Firestore client once per project (thread-safe, shared by all sessions).

    Args:
        project: GCP project id hosting the `(default)` database.

    Returns:
        The Firestore client.
    """
    return firestore.Client(project=project)


def _document(session_id: str) -> Any:
    """Reference a session document in SESSIONS_COLLECTION.

    Args:
        session_id: The session's UUID4, also the document id.

    Returns:
        The Firestore DocumentReference.
    """
    settings = get_settings()
    collection = _client(settings.gcp_project_id).collection(settings.sessions_collection)
    return collection.document(session_id)


def create_session(mode: Literal["guest", "spotify"]) -> SessionState:
    """Create a session with a server-generated UUID4 (one set()).

    Args:
        mode: Initial mode of the conversation.

    Returns:
        The new session state.
    """
    now = _now()
    session_id, expires_at = str(uuid.uuid4()), expiry(now)
    state = SessionState(
        session_id=session_id, created_at=now, last_message_at=now, expires_at=expires_at, mode=mode
    )
    _document(session_id).set(state.model_dump())
    return state


def load_session(session_id: str) -> tuple[SessionStatus, SessionState | None]:
    """Read a session (one get()); expired or unreadable documents are deleted on read.

    Args:
        session_id: The id read from the browser.

    Returns:
        ("active", state), or ("missing" | "expired", None).
    """
    snapshot = _document(session_id).get()
    if not snapshot.exists:
        return "missing", None
    try:
        state: SessionState | None = SessionState.model_validate(snapshot.to_dict())
    except ValidationError:
        logging.getLogger(__name__).warning("Deleting unreadable session %s", session_id)
        state = None
    if state is None or is_expired(state):
        _document(session_id).delete()
        return ("missing" if state is None else "expired"), None
    return "active", state


def save_turn(state: SessionState, new_messages: list[ChatMessage], **changes: Any) -> SessionState:
    """Append messages, apply changes and slide both timestamps (one update()).

    Args:
        state: The cached session state.
        new_messages: Messages of this turn, in order.
        **changes: Other field changes (draft, resolved_tracks, pending_action...).

    Returns:
        The new session state, as written.
    """
    now = _now()
    messages = [*state.messages, *new_messages]
    merged = merge_state(state, messages, **changes, last_message_at=now, expires_at=expiry(now))
    _document(merged.session_id).update(merged.model_dump(exclude=set(IMMUTABLE_FIELDS)))
    return merged


def touch(state: SessionState, **changes: Any) -> SessionState:
    """Apply changes and slide the expiry, keeping `last_message_at` (one update()).

    Args:
        state: The cached session state.
        **changes: Field changes (pending_action, oauth_state, spotify_auth, mode...).

    Returns:
        The new session state, as written.
    """
    merged = merge_state(state, list(state.messages), **changes, expires_at=expiry(_now()))
    _document(merged.session_id).update(merged.model_dump(exclude=set(IMMUTABLE_FIELDS)))
    return merged


def is_expired(state: SessionState) -> bool:
    """Check expiry on the cached state (no Firestore read).

    Args:
        state: The cached session state.

    Returns:
        True when `expires_at` is now or in the past.
    """
    return state.expires_at <= _now()


def delete_session(session_id: str) -> None:
    """Hard-delete the conversation, draft and encrypted tokens (New chat).

    Args:
        session_id: The session to delete.
    """
    _document(session_id).delete()
