"""Base class and shared field types of the validated configuration sections."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]  # Non-blank string


class Section(BaseModel):
    """Base of every section: immutable, strict types (no "16" for 16), unknown keys rejected."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
