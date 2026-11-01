"""Deterministic clean-up of the playlist title the LLM generates.

The prompt asks for a short title, but the bound is enforced here: the title becomes the
Spotify playlist name, which must never be blank (`POST /me/playlists` requires `name`).
"""

MAX_TITLE_LENGTH = 60  # Longest title kept, so it fits the card header and Spotify's lists
FALLBACK_TITLE = "My AI Playlist"  # Used when the LLM returns a blank title
WRAPPING_QUOTES = '"“”'  # Quotes stripped from both ends; not ' (apostrophe in "Rockin'")


def clean_title(title: str) -> str:
    """Collapse whitespace, strip wrapping double quotes, cap the length, fill a blank title.

    Args:
        title: The title returned by the LLM.

    Returns:
        A single-line title of at most MAX_TITLE_LENGTH characters, never blank.
    """
    single_line = " ".join(title.split()).strip(WRAPPING_QUOTES).strip()
    if len(single_line) > MAX_TITLE_LENGTH:
        single_line = single_line[: MAX_TITLE_LENGTH - 1].rstrip() + "…"
    return single_line or FALLBACK_TITLE
