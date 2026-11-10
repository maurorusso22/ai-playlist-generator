"""Stand-ins for Anthropic SDK responses, shared by the Claude engine tests."""

from types import SimpleNamespace

from src.models.conversation.assistant_turn import AssistantTurn
from src.models.conversation.playlist_criteria import PlaylistCriteria

CLARIFY = AssistantTurn(  # A valid reply that the guard leaves unchanged
    intent="clarify", criteria=PlaylistCriteria(), message="Which mood?"
)
PAUSED_PARAM = {  # What a paused response turns into when it is sent back
    "role": "assistant",
    "content": [{"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search"}],
}


def claude_response(
    *texts: str, stop_reason: str = "end_turn", searches: int = 0
) -> SimpleNamespace:
    """Build a Messages API response: an empty thinking block, then one text block per text.

    Args:
        texts: Contents of the text blocks, in order.
        stop_reason: Why the model stopped.
        searches: Web searches reported in the usage.

    Returns:
        A stand-in for `anthropic.types.Message`.
    """
    details = SimpleNamespace(category="cyber") if stop_reason == "refusal" else None
    blocks = [SimpleNamespace(type="thinking", thinking="")]
    blocks += [SimpleNamespace(type="text", text=text) for text in texts]
    usage = SimpleNamespace(server_tool_use=SimpleNamespace(web_search_requests=searches))
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=details,
        content=blocks,
        usage=usage,
        to_param=lambda: PAUSED_PARAM,
    )
