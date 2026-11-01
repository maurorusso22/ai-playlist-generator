"""Deterministic guard on the LLM's structured reply: minimum criteria and playlist size.

The rules live here, in testable Python, so they hold even when the LLM ignores the prompt:
a playlist needs at least one of six references (unless a draft already exists), and its
size is always clamped to the configured bounds and its title cleaned, whatever the LLM returns.
"""

import math
import unicodedata

from src.config.constants import OVERGENERATION_RATIO, PLAYLIST_HARD_MAX_SIZE, PLAYLIST_MIN_SIZE
from src.config.settings import get_settings
from src.conversation.prompt import CLARIFICATION_FALLBACK
from src.conversation.title import clean_title
from src.models.conversation.assistant_turn import AssistantTurn
from src.models.conversation.playlist_criteria import PlaylistCriteria
from src.models.conversation.playlist_draft import PlaylistDraft

PLAYLIST_INTENTS = frozenset({"propose_playlist", "revise_playlist"})  # Intents carrying a draft
REFERENCE_FIELDS = ("genres", "moods", "years", "artists", "albums", "songs")  # The 6 references
RATIO_DIGITS = 9  # Rounding before ceil, so float noise (3.0000000000000004) adds no track


def has_minimum_criteria(criteria: PlaylistCriteria) -> bool:
    """Check that at least one of the six references is known; other_constraints do not count.

    Args:
        criteria: Criteria extracted by the LLM from the whole conversation.

    Returns:
        True if any of genres, moods, years, artists, albums or songs has a non-blank value.
    """
    return any(value.strip() for name in REFERENCE_FIELDS for value in getattr(criteria, name))


def clamp_size(requested: int | None) -> int:
    """Clamp a requested playlist size to [PLAYLIST_MIN_SIZE, playlist.max_size].

    `playlist.max_size` may lower the cap but never raise it above `PLAYLIST_HARD_MAX_SIZE`.

    Args:
        requested: Size the user asked for, or None when they gave no number.

    Returns:
        The size to build: the default size for None, otherwise the clamped value.
    """
    settings = get_settings()
    if requested is None:
        return settings.playlist.default_size
    upper = min(settings.playlist.max_size, PLAYLIST_HARD_MAX_SIZE)
    return max(PLAYLIST_MIN_SIZE, min(requested, upper))


def candidate_count(size: int) -> int:
    """Number of LLM candidates for a playlist size, with over-generation.

    Args:
        size: Final playlist size, already clamped.

    Returns:
        size + ceil(size * OVERGENERATION_RATIO), e.g. 20 for 16.
    """
    return size + math.ceil(round(size * OVERGENERATION_RATIO, RATIO_DIGITS))


def _normalize(text: str) -> str:
    """Normalize text for duplicate detection: case, accents and spacing are ignored.

    Args:
        text: A track title or artist name.

    Returns:
        The casefolded, accent-free text with single spaces.
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def _clean_playlist(draft: PlaylistDraft) -> PlaylistDraft:
    """Clamp the target size, clean the title, drop blank and duplicate tracks, cap the count.

    Args:
        draft: The playlist as returned by the LLM.

    Returns:
        A new draft that respects the size bounds.
    """
    size = clamp_size(draft.target_size)
    seen: set[tuple[str, str]] = set()
    tracks = []
    for track in draft.tracks:
        key = (_normalize(track.title), _normalize(track.artist))
        if all(key) and key not in seen:
            seen.add(key)
            tracks.append(track)
    update = {
        "title": clean_title(draft.title),
        "target_size": size,
        "tracks": tracks[: candidate_count(size)],
    }
    cleaned: PlaylistDraft = draft.model_copy(update=update)
    return cleaned


def apply_guard(turn: AssistantTurn, has_draft: bool) -> AssistantTurn:
    """Enforce the minimum-criteria rule and the size bounds on an LLM turn.

    A playlist intent without any reference and without an existing draft becomes a
    clarification with `CLARIFICATION_FALLBACK`; a playlist intent with no usable playlist
    becomes a clarification that keeps the LLM message; other intents never carry a playlist.

    Args:
        turn: The structured reply returned by the LLM.
        has_draft: Whether the session already holds a draft (revisions need no new criteria).

    Returns:
        A new, guarded turn; the input turn is never modified.
    """
    if turn.intent not in PLAYLIST_INTENTS:
        update: dict[str, object] = {"playlist": None}
    elif not has_draft and not has_minimum_criteria(turn.criteria):
        update = {"intent": "clarify", "message": CLARIFICATION_FALLBACK, "playlist": None}
    else:
        playlist = _clean_playlist(turn.playlist) if turn.playlist is not None else None
        usable = playlist is not None and bool(playlist.tracks)
        update = {"playlist": playlist} if usable else {"intent": "clarify", "playlist": None}
    guarded: AssistantTurn = turn.model_copy(update=update)
    return guarded
