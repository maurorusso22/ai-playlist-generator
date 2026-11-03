"""Unit tests for the conversation chain with a mocked Gemini model (offline)."""

from collections.abc import Iterator
from typing import Literal, cast
from unittest.mock import MagicMock

import pytest
from google.genai.errors import ClientError, ServerError
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai.chat_models import GoogleRateLimitError
from pytest_mock import MockerFixture

from src.conversation import chain
from src.conversation.prompt import CLARIFICATION_FALLBACK, format_draft_context
from src.models.conversation.assistant_turn import AssistantTurn
from src.models.conversation.playlist_criteria import PlaylistCriteria
from src.models.conversation.playlist_draft import PlaylistDraft
from src.models.session.chat_message import ChatMessage
from src.models.spotify.resolved_track import ResolvedTrack

Intent = Literal["clarify", "propose_playlist", "revise_playlist", "off_topic"]  # Turn intents
ANIMALS = {"title": "Animals", "artist": "Martin Garrix"}  # A well-known house track
DRAFT = PlaylistDraft.model_validate(  # The LLM's own previous draft
    {"title": "House", "description": "Hits", "target_size": 1, "tracks": [ANIMALS, ANIMALS]}
)
SPOTIFY_MARKERS = ("open.spotify.com", "spotify:track:", "i.scdn.co")  # Must never reach the LLM


def _turn(
    intent: Intent, criteria: PlaylistCriteria | None = None, draft: bool = True
) -> AssistantTurn:
    """Build a canned LLM turn.

    Args:
        intent: Turn intent.
        criteria: Extracted criteria, empty by default.
        draft: Whether the turn carries DRAFT.

    Returns:
        The canned turn.
    """
    criteria = criteria or PlaylistCriteria()
    playlist = DRAFT if draft else None
    return AssistantTurn(intent=intent, criteria=criteria, message="Hi", playlist=playlist)


@pytest.fixture
def invoke(mocker: MockerFixture) -> Iterator[MagicMock]:
    """Patch Gemini and expose the structured runnable's `invoke`.

    Args:
        mocker: pytest-mock fixture.

    Returns:
        The mocked `invoke`, yielded; the lazily built LLM cache is cleared around each test.
    """
    chain._build_llm.cache_clear()
    llm_cls = mocker.patch("src.conversation.chain.ChatGoogleGenerativeAI")
    yield llm_cls.return_value.with_structured_output.return_value.invoke
    chain._build_llm.cache_clear()


def test_run_turn_sends_size_rules_and_returns_a_turn(invoke: MagicMock) -> None:
    """The first message is a SystemMessage with the size rules; the model uses the settings."""
    invoke.return_value = _turn("propose_playlist", PlaylistCriteria(genres=["house"]))
    assert isinstance(chain.run_turn("House please", [], None), AssistantTurn)
    system = invoke.call_args.args[0][0]
    assert isinstance(system, SystemMessage)
    assert "or 16 if they" in system.content and "between 1 and 30" in system.content
    assert "20 tracks for 16, 36 for 30" in system.content
    llm_cls = getattr(chain, "ChatGoogleGenerativeAI")  # Patched by the invoke fixture
    llm_cls.assert_called_once_with(
        model="gemini-3.5-flash-lite", google_api_key="test-google-api-key", max_retries=2
    )


def test_history_maps_roles_skips_notices_and_is_capped(invoke: MagicMock) -> None:
    """Roles map to Human/AI messages, notices are dropped, only the last 20 are sent."""
    invoke.return_value = _turn("clarify", draft=False)
    history: list[ChatMessage] = []
    for i in range(15):
        history += [
            ChatMessage(role="user", content=f"user {i}"),
            ChatMessage(role="notice", content=f"notice {i}"),
            ChatMessage(role="assistant", content=f"assistant {i}"),
        ]
    chain.run_turn("next", history, None)
    sent = invoke.call_args.args[0]
    middle = sent[1:-1]
    assert len(middle) == chain.HISTORY_MAX_MESSAGES == 20
    assert [m.content for m in middle[:2]] == ["user 5", "assistant 5"]
    assert [type(m) for m in middle] == [HumanMessage, AIMessage] * 10
    assert not any("notice" in m.content for m in sent)
    assert isinstance(sent[-1], HumanMessage) and sent[-1].content == "next"


def test_new_message_already_in_history_is_sent_once(invoke: MagicMock) -> None:
    """A trailing copy of the new user message in the history is not duplicated."""
    invoke.return_value = _turn("clarify", draft=False)
    chain.run_turn("rock", [ChatMessage(role="user", content="rock")], None)
    assert [m.content for m in invoke.call_args.args[0][1:]] == ["rock"]


def test_draft_context_has_titles_and_never_spotify_data(invoke: MagicMock) -> None:
    """Only the LLM's own title/artist pairs are sent, even if the caller holds resolved data."""
    resolved = ResolvedTrack(name="Animals", artists=["Garrix"], uri="spotify:track:a")
    links = "https://open.spotify.com/playlist/xyz https://i.scdn.co/image/abc"
    invoke.return_value = _turn("revise_playlist")
    chain.run_turn("Shorter", [ChatMessage(role="notice", content=f"Saved: {links}")], DRAFT)
    sent = invoke.call_args.args[0]
    assert "1. Animals — Martin Garrix\n2. Animals — Martin Garrix" in sent[0].content
    assert not any(marker in m.content for marker in SPOTIFY_MARKERS for m in sent)
    with pytest.raises(TypeError):
        format_draft_context(cast(PlaylistDraft, resolved))
    assert format_draft_context(None) == ""


def test_guard_overrides_proposal_without_criteria(invoke: MagicMock) -> None:
    """A propose_playlist turn with no criterion and no draft becomes a clarification."""
    invoke.return_value = _turn("propose_playlist")
    turn = chain.run_turn("Make me a playlist", [], None)
    assert (turn.intent, turn.message, turn.playlist) == ("clarify", CLARIFICATION_FALLBACK, None)


def test_off_topic_has_no_playlist(invoke: MagicMock) -> None:
    """An off_topic turn never carries a playlist."""
    invoke.return_value = _turn("off_topic", PlaylistCriteria(genres=["rock"]))
    assert chain.run_turn("Weather in Rome?", [], None).playlist is None


def test_parse_failure_is_retried_once_then_reported_unavailable(invoke: MagicMock) -> None:
    """One parsing failure is retried; a second one (or a non-AssistantTurn result) raises."""
    invoke.side_effect = [OutputParserException("bad json"), _turn("clarify", draft=False)]
    assert chain.run_turn("Hi", [], None).intent == "clarify"
    assert invoke.call_count == 2
    invoke.side_effect = [OutputParserException("bad json"), None]
    with pytest.raises(chain.AssistantUnavailableError):
        chain.run_turn("Hi", [], None)
    assert invoke.call_count == 4


def test_gemini_errors_propagate_without_retry(invoke: MagicMock) -> None:
    """Wrapped ClientErrors surface as the original ClientError; ServerErrors propagate."""
    original = ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}})
    wrapped = GoogleRateLimitError("Error calling model")
    wrapped.__cause__ = original
    invoke.side_effect = [wrapped, ServerError(503, {"error": {"code": 503}})]
    with pytest.raises(ClientError) as client_error:
        chain.run_turn("Hi", [], None)
    assert client_error.value is original and client_error.value.code == 429
    with pytest.raises(ServerError):
        chain.run_turn("Hi", [], None)
    assert invoke.call_count == 2
