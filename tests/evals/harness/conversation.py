"""Multi-turn conversations through the production chain, threaded as the app threads them."""

from dataclasses import dataclass

from src.conversation import chain
from src.models.conversation.assistant_turn import AssistantTurn
from src.models.conversation.playlist_draft import PlaylistDraft
from src.models.session.chat_message import ChatMessage
from tests.evals.harness.live import timed_with_retry


@dataclass(frozen=True)
class ConversationRun:
    """The last turn of a conversation, the draft it started from and every call's latency."""

    final: AssistantTurn
    previous_draft: PlaylistDraft | None
    latencies: tuple[float, ...]


def _turn(
    model: str, text: str, history: list[ChatMessage], draft: PlaylistDraft | None
) -> tuple[AssistantTurn, float]:
    """Run one paced, guarded turn with retries on transient errors.

    Args:
        model: Model id the chain is configured with.
        text: The user message.
        history: Messages before it.
        draft: The LLM's own current draft, or None.

    Returns:
        The guarded turn and its latency in seconds.
    """
    return timed_with_retry(model, lambda: chain.run_turn(text, history, draft))


def run_conversation(turns: list[str], model: str) -> ConversationRun:
    """Send the user messages in order, keeping history and draft like `src/ui/turn.py`.

    Only user/assistant text and the LLM's own draft are carried over: no Spotify data.

    Args:
        turns: The user messages.
        model: Model id the chain is configured with, for pacing.

    Returns:
        The final turn, the draft before it and the latencies.
    """
    history: list[ChatMessage] = []
    draft: PlaylistDraft | None = None
    previous: PlaylistDraft | None = None
    latencies: list[float] = []
    final: AssistantTurn | None = None
    for text in turns:
        previous = draft
        final, elapsed = _turn(model, text, list(history), draft)
        latencies.append(elapsed)
        history += [
            ChatMessage(role="user", content=text),
            ChatMessage(role="assistant", content=final.message),
        ]
        if final.playlist is not None:  # Clarifications and off-topic replies keep the draft
            draft = final.playlist
    if final is None:
        raise ValueError("A conversation needs at least one user message")
    return ConversationRun(final=final, previous_draft=previous, latencies=tuple(latencies))
