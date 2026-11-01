"""Theme injection and the small, static HTML effects of the UI.

The stylesheet lives in `public/styles.css` (it would not fit the module size budget); this
module loads it and builds trusted HTML snippets that contain no user or Spotify data. Every
animation is disabled by the stylesheet under `prefers-reduced-motion`.
"""

import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st

PUBLIC_DIR = Path(__file__).resolve().parents[2] / "public"  # Static assets folder
STYLESHEET = PUBLIC_DIR / "styles.css"  # Theme, glass surfaces, animations
LOGO = PUBLIC_DIR / "logo.svg"  # App logo authored for this project
EQUALIZER_BARS = 4  # Bars in the typing indicator
CONFETTI_PIECES = 36  # Confetti pieces dropped when a playlist is created
CONFETTI_COLORS = ("#A855F7", "#C084FC", "#7C3AED", "#EDE9FE", "#D946EF")  # Violet palette
MIME_TYPES = {".svg": "image/svg+xml", ".png": "image/png"}  # Asset types embeddable inline


def inject_styles() -> None:
    """Load the stylesheet; style-only HTML goes to Streamlit's event container (no gap)."""
    st.html(STYLESHEET)


@lru_cache(maxsize=4)
def data_uri(path: Path) -> str | None:
    """Encode a local image as a data URI, so no static file server is needed.

    Args:
        path: Image file under `public/`.

    Returns:
        The data URI, or None when the file does not exist.
    """
    if not path.is_file():
        return None
    encoded = base64.b64encode(path.read_bytes()).decode()
    return f"data:{MIME_TYPES.get(path.suffix, 'application/octet-stream')};base64,{encoded}"


def logo_html(size: int) -> str:
    """Build the app logo as an inline image.

    Args:
        size: Width and height in pixels.

    Returns:
        An <img> tag, or an empty string when the asset is missing.
    """
    uri = data_uri(LOGO)
    if uri is None:
        return ""
    return f'<img src="{uri}" alt="AI Playlist Generator logo" width="{size}" height="{size}">'


def brand_html() -> str:
    """Build the compact brand line shown in the chat header.

    Returns:
        The logo and the app name.
    """
    return f'<div class="apg-brand">{logo_html(28)}<span>AI Playlist Generator</span></div>'


def equalizer_html() -> str:
    """Build the equalizer-bars typing indicator.

    Returns:
        The indicator markup.
    """
    bars = "<span></span>" * EQUALIZER_BARS
    return f'<div class="apg-eq" role="status" aria-label="Thinking">{bars}</div>'


def skeleton_rows_html(n: int) -> str:
    """Build shimmering placeholder rows shown while tracks are resolved.

    Args:
        n: Number of placeholder rows.

    Returns:
        The skeleton markup.
    """
    row = (
        '<div class="apg-skel"><div class="apg-skel-cover apg-shimmer"></div>'
        '<div class="apg-skel-lines"><div class="apg-skel-line apg-shimmer"></div>'
        '<div class="apg-skel-line short apg-shimmer"></div></div></div>'
    )
    return f'<div class="apg-card" aria-hidden="true">{row * max(n, 0)}</div>'


def confetti_html() -> str:
    """Build the CSS confetti; positions are spread deterministically, no randomness needed.

    Returns:
        The confetti overlay markup.
    """
    pieces = []
    for i in range(CONFETTI_PIECES):
        color = CONFETTI_COLORS[i % len(CONFETTI_COLORS)]
        left, delay = (i * 37) % 100, (i * 53) % 900 / 1000
        style = f"left:{left}%;background:{color};animation-delay:{delay:.2f}s"
        pieces.append(f'<i style="{style}"></i>')
    return f'<div class="apg-confetti" aria-hidden="true">{"".join(pieces)}</div>'


def celebrate() -> None:
    """Drop violet confetti once; hidden by the stylesheet under reduced motion."""
    st.markdown(confetti_html(), unsafe_allow_html=True)
