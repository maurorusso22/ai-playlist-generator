"""The playlist already created on Spotify for the current draft."""

from pydantic import BaseModel


class CreatedPlaylist(BaseModel):
    """A playlist already created on Spotify; `items_added` lets a retry resume at add_items."""

    id: str
    url: str
    items_added: bool = False
