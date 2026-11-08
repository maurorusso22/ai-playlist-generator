"""Deterministic checks on a conversation's final turn: intent, size, title, criteria, message.

`evaluate` is the entry point: it adds the always-on checks (a playlist holds exactly the
over-generated candidate count) to the expectations each case sets.
"""

import unicodedata

from src.conversation.criteria import candidate_count
from src.models.conversation.playlist_criteria import PlaylistCriteria
from tests.evals.harness.cases import CriteriaExpect, Expect
from tests.evals.harness.conversation import ConversationRun
from tests.evals.harness.language import detect_language
from tests.evals.harness.track_checks import track_checks


def _fold(text: str) -> str:
    """Casefold and strip accents, for substring comparisons.

    Args:
        text: Any text.

    Returns:
        The folded text.
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _criteria_ok(criteria: PlaylistCriteria, expected: CriteriaExpect) -> bool:
    """Check that every expected substring appears in some value of its criteria list.

    Args:
        criteria: Criteria the LLM extracted.
        expected: Substrings per field.

    Returns:
        True when every expected substring is found.
    """
    for field, wanted in expected.model_dump().items():
        values = [_fold(v) for v in getattr(criteria, field)]
        if not all(any(_fold(w) in v for v in values) for w in wanted):
            return False
    return True


def evaluate(run: ConversationRun, expect: Expect) -> dict[str, bool]:
    """Run every check that applies to a conversation's final turn.

    Args:
        run: The conversation result.
        expect: The case's expectations.

    Returns:
        Check name → passed.
    """
    turn, playlist = run.final, run.final.playlist
    message = _fold(turn.message)
    checks = {"intent": turn.intent in expect.intent}
    if playlist is not None:
        checks["candidates"] = len(playlist.tracks) == candidate_count(playlist.target_size)
    if expect.language is not None:
        checks["language"] = detect_language(turn.message) == expect.language
    if expect.target_size is not None:
        checks["target_size"] = playlist is not None and playlist.target_size == expect.target_size
    if expect.title is not None:
        checks["title"] = playlist is not None and playlist.title == expect.title
    if expect.title_unchanged:
        before = run.previous_draft.title if run.previous_draft else None
        checks["title_unchanged"] = playlist is not None and playlist.title == before
    if any(expect.criteria.model_dump().values()):
        checks["criteria"] = _criteria_ok(turn.criteria, expect.criteria)
    if expect.message_contains:
        checks["message_contains"] = all(_fold(s) in message for s in expect.message_contains)
    if expect.message_excludes:
        checks["message_excludes"] = not any(_fold(s) in message for s in expect.message_excludes)
    return checks | track_checks(playlist, run.previous_draft, expect)
