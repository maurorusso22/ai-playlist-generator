"""Eval case schemas and the YAML dataset loader; typos in a dataset fail loudly."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

DATASETS_DIR = Path(__file__).resolve().parents[1] / "datasets"  # YAML eval datasets

Intent = Literal["clarify", "propose_playlist", "revise_playlist", "off_topic"]  # Turn intents
Language = Literal["it", "en", "es"]  # Languages the stopword detector recognizes


class _Strict(BaseModel):
    """Base of every schema: unknown keys are rejected, so a misspelled check is an error."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class GateCase(_Strict):
    """One message for the intent gate, labeled by the gate's own lenient policy."""

    id: str
    text: str
    label: Literal["IN", "OUT"]
    context: str | None = None  # The assistant's last reply, when the message answers it


class CriteriaExpect(_Strict):
    """Substrings each criteria list must contain (case and accent insensitive)."""

    genres: list[str] = []
    moods: list[str] = []
    years: list[str] = []
    artists: list[str] = []
    albums: list[str] = []
    songs: list[str] = []
    other_constraints: list[str] = []


class Expect(_Strict):
    """Deterministic expectations on the final turn of a conversation."""

    intent: list[Intent] = Field(min_length=1)
    language: Language | None = None
    target_size: int | None = None
    title: str | None = None
    title_unchanged: bool = False
    criteria: CriteriaExpect = CriteriaExpect()
    includes_artists: list[str] = []
    excludes_artists: list[str] = []
    only_artists: list[str] = []
    excludes_titles: list[str] = []
    year_range: tuple[int, int] | None = None
    message_contains: list[str] = []
    message_excludes: list[str] = []
    keeps_previous: float | None = Field(default=None, ge=0, le=1)


class ConversationCase(_Strict):
    """User messages sent in order; the checks apply to the last turn."""

    id: str
    turns: list[str] = Field(min_length=1)
    expect: Expect


class ExistenceCase(_Strict):
    """One playlist request whose suggestions are looked up on Spotify."""

    id: str
    request: str


def load_cases[CaseT: BaseModel](file_name: str, schema: type[CaseT]) -> list[CaseT]:
    """Load and validate a YAML dataset.

    Args:
        file_name: Dataset file inside DATASETS_DIR.
        schema: Pydantic model of one case.

    Returns:
        The validated cases, in file order.
    """
    with (DATASETS_DIR / file_name).open(encoding="utf-8") as file:
        items = yaml.safe_load(file)
    return [schema.model_validate(item) for item in items]
