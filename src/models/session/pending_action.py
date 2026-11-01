"""Confirmation buttons waiting for a click."""

from typing import Literal

from pydantic import BaseModel


class PendingAction(BaseModel):
    """Confirmation buttons, bound to the message they render under."""

    kind: Literal["confirm_create", "login_to_save"]
    message_index: int
