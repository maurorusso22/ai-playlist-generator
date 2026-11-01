"""A track proposed by the LLM: part of its structured output and the resolver's input."""

from pydantic import BaseModel, Field


class TrackSuggestion(BaseModel):
    """A track proposed by the LLM; the resolver's input."""

    title: str = Field(description="Track title.")
    artist: str = Field(description="Main artist.")
    album: str | None = Field(default=None, description="Album, if known.")
    year: int | None = Field(default=None, description="Release year, if known.")
