"""Shared, safe HTML pieces for Spotify content: URL allowlist and the official logo.

Used by the playlist card and the saved-playlist card, the only places where Spotify data
meets raw HTML: only Spotify's own link and image hosts ever reach an attribute.
"""

import html

from src.ui import styles

TRACK_URL_PREFIX = "https://open.spotify.com/"  # Only links to Spotify's web player are kept
IMAGE_URL_PREFIX = "https://i.scdn.co/"  # Only Spotify's image CDN is kept
SPOTIFY_LOGOS = (  # Official full logos, unmodified: (CSS theme class, file) per surface
    ("light", styles.PUBLIC_DIR / "spotify_logo_black.svg"),
    ("dark", styles.PUBLIC_DIR / "spotify_logo_white.svg"),
)
LOGO_PX = 24  # Full logo height; its width (~88px) stays above Spotify's 70px minimum


def safe_url(url: str | None, prefix: str) -> str | None:
    """Accept a URL only on an allowlisted host, escaped for an HTML attribute.

    Args:
        url: URL coming from Spotify data.
        prefix: Required scheme, host and leading slash.

    Returns:
        The escaped URL, or None when it is missing or not allowlisted.
    """
    if not url or not url.startswith(prefix):
        return None
    return html.escape(url, quote=True)


def spotify_logo_html() -> str:
    """Build both variants of the full Spotify logo; the stylesheet shows the matching one.

    Returns:
        The logo markup, empty when the logo files are missing.
    """
    uris = ((theme, styles.data_uri(path)) for theme, path in SPOTIFY_LOGOS)
    return "".join(
        f'<img class="apg-logo-{theme}" src="{uri}" alt="Spotify" height="{LOGO_PX}">'
        for theme, uri in uris
        if uri
    )
