"""The user's cumulative playlist criteria, extracted by the LLM.

Field descriptions are short instructions for the LLM (`with_structured_output`).
"""

from pydantic import BaseModel, Field


class PlaylistCriteria(BaseModel):
    """Everything the user asked for so far, across the whole conversation."""

    genres: list[str] = Field(default_factory=list, description="Genres, e.g. house.")
    moods: list[str] = Field(default_factory=list, description="Moods or activities.")
    years: list[str] = Field(default_factory=list, description="Years or eras, e.g. 2010s.")
    artists: list[str] = Field(default_factory=list, description="Artists mentioned.")
    albums: list[str] = Field(default_factory=list, description="Albums mentioned.")
    songs: list[str] = Field(default_factory=list, description="Songs mentioned.")
    other_constraints: list[str] = Field(
        default_factory=list, description='Other constraints, e.g. "danceable", "no remixes".'
    )
